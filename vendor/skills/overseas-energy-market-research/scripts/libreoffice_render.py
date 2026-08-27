from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_TIMEOUT_SECONDS = 120


def prepend_bundled_runtime_bin() -> None:
    python_root = Path(sys.executable).resolve().parent
    dependencies_root = python_root.parent if python_root.name == "python" else None
    if dependencies_root and dependencies_root.name == "dependencies":
        runtime_bin = dependencies_root / "bin" / "override"
        if runtime_bin.is_dir():
            entries = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
            os.environ["PATH"] = os.pathsep.join(
                [str(runtime_bin), *[p for p in entries if Path(p) != runtime_bin]]
            )


def resolve_soffice() -> str:
    override = os.environ.get("SOFFICE_PATH", "").strip()
    if override:
        path = Path(override).expanduser()
        if path.exists():
            return str(path.resolve())
        raise FileNotFoundError(f"SOFFICE_PATH does not exist: {path}")

    if os.name == "nt":
        found = shutil.which("soffice.com") or shutil.which("soffice.exe")
        if found:
            return found
        for candidate in (
            Path(r"C:\Program Files\LibreOffice\program\soffice.com"),
            Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.com"),
        ):
            if candidate.exists():
                return str(candidate)
    else:
        found = shutil.which("soffice") or shutil.which("libreoffice")
        if found:
            return found
    raise FileNotFoundError("LibreOffice soffice was not found. Install LibreOffice or set SOFFICE_PATH.")


def profile_uri(profile_dir: Path) -> str:
    """Return a valid LibreOffice UserInstallation URI on every platform."""
    return profile_dir.resolve().as_uri()


def build_env(profile_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    if os.name == "nt":
        env["TEMP"] = str(profile_dir)
        env["TMP"] = str(profile_dir)
    else:
        env["HOME"] = str(profile_dir)
        env["XDG_CONFIG_HOME"] = str(profile_dir / "xdg_config")
        env["XDG_CACHE_HOME"] = str(profile_dir / "xdg_cache")
        Path(env["XDG_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
        Path(env["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)
    return env


def kill_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run_bounded(
    command: list[str], env: dict[str, str], timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, object] = {
        "args": command,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        # Windows 下 soffice.com 输出 GBK，UTF-8 解码会抛 UnicodeDecodeError（曾致渲染流程中断）
        "encoding": "gbk" if os.name == "nt" else "utf-8",
        "errors": "replace",
        "env": env,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(**kwargs)
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
        return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        kill_process_tree(proc)
        stdout, stderr = proc.communicate()
        stderr = (stderr or "") + f"\nTimed out after {timeout_seconds} seconds."
        return subprocess.CompletedProcess(command, 124, stdout or "", stderr)


def pdf_filter(input_path: Path) -> str:
    ext = input_path.suffix.lower()
    if ext in {".doc", ".docx", ".docm", ".dot", ".dotx", ".odt"}:
        return "pdf:writer_pdf_Export"
    if ext in {".ppt", ".pptx", ".pptm", ".odp"}:
        return "pdf:impress_pdf_Export"
    if ext in {".xls", ".xlsx", ".xlsm", ".ods"}:
        return "pdf:calc_pdf_Export"
    return "pdf"


def convert_to_pdf(input_path: Path, output_dir: Path, timeout_seconds: int) -> Path:
    soffice = resolve_soffice()
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lo_profile_") as profile_raw:
        profile = Path(profile_raw)
        command = [
            soffice,
            f"-env:UserInstallation={profile_uri(profile)}",
            "--headless",
            "--invisible",
            "--nologo",
            "--nodefault",
            "--nofirststartwizard",
            "--norestore",
            "--convert-to",
            pdf_filter(input_path),
            "--outdir",
            str(output_dir),
            str(input_path),
        ]
        result = run_bounded(command, build_env(profile), timeout_seconds)

    expected = output_dir / f"{input_path.stem}.pdf"
    candidates = [expected, *sorted(output_dir.glob("*.pdf"))]
    pdf = next((p for p in candidates if p.exists() and p.stat().st_size > 0), None)
    if result.returncode != 0 or pdf is None:
        detail = "\n".join(
            part
            for part in (
                "CMD: " + " ".join(command),
                f"EXIT: {result.returncode}",
                "STDOUT:\n" + result.stdout.strip() if result.stdout else "",
                "STDERR:\n" + result.stderr.strip() if result.stderr else "",
            )
            if part
        )
        raise RuntimeError("LibreOffice conversion failed.\n" + detail)
    return pdf


def render_pdf_pages(pdf_path: Path, output_dir: Path, dpi: int) -> list[Path]:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for PDF page rendering. Install it with: "
            "python -m pip install PyMuPDF"
        ) from exc

    # LibreOffice PDFs can contain a valid but non-essential structure tree that
    # triggers MuPDF's "No common ancestor" diagnostic while pages still render
    # correctly. Keep CLI output actionable; actual open/render failures still
    # raise Python exceptions and remain hard failures.
    try:
        pymupdf.TOOLS.mupdf_display_errors(False)
    except AttributeError:
        pass

    output_dir.mkdir(parents=True, exist_ok=True)
    scale = dpi / 72.0
    matrix = pymupdf.Matrix(scale, scale)
    with pymupdf.open(pdf_path) as document:
        if document.page_count == 0:
            raise RuntimeError(f"PDF has no pages: {pdf_path}")
        # Render into a staging directory first. Existing page PNGs are replaced
        # only after every page succeeds, so a failed render cannot leave a
        # partially updated QA directory.
        with tempfile.TemporaryDirectory(prefix="pymupdf_pages_", dir=output_dir) as staged_raw:
            staged_dir = Path(staged_raw)
            staged_pages: list[Path] = []
            for page_number, page in enumerate(document, start=1):
                target = staged_dir / f"page-{page_number}.png"
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                target.write_bytes(pixmap.tobytes("png"))
                staged_pages.append(target)

            for stale in output_dir.glob("page-*.png"):
                stale.unlink()
            pages: list[Path] = []
            for staged_page in staged_pages:
                target = output_dir / staged_page.name
                staged_page.replace(target)
                pages.append(target)
    return pages


def update_word_manifest(
    manifest_path: Path,
    output_dir: Path,
    pdf_path: Path,
    pages: list[Path],
    mark_pages_inspected: bool,
) -> None:
    if not manifest_path.exists():
        raise FileNotFoundError(f"Word production manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    manifest["rendering"] = {
        "status": "passed" if mark_pages_inspected else "rendered",
        "page_count": len(pages),
        "pages_inspected": len(pages) if mark_pages_inspected else 0,
        "render_dir": str(output_dir),
        "issues": [],
    }
    manifest.setdefault("pdf", {})["qa_export_path"] = str(pdf_path)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert Office files with an isolated, timeout-safe LibreOffice profile."
    )
    parser.add_argument("input_path")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--render-pages", action="store_true")
    parser.add_argument("--word-manifest", help="Update a Word production manifest with render results.")
    parser.add_argument(
        "--mark-pages-inspected",
        action="store_true",
        help="Record every rendered page as inspected; use only after actual visual review.",
    )
    parser.add_argument("--dpi", type=int, default=120)
    args = parser.parse_args()

    input_path = Path(args.input_path).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be positive")
    if args.dpi <= 0:
        raise ValueError("--dpi must be positive")

    prepend_bundled_runtime_bin()
    output_dir.mkdir(parents=True, exist_ok=True)
    # Convert into a fresh directory so stale PDFs in a reused QA directory can
    # never be mistaken for the result of the current LibreOffice invocation.
    with tempfile.TemporaryDirectory(prefix="lo_convert_") as conversion_raw:
        converted = convert_to_pdf(input_path, Path(conversion_raw), args.timeout_seconds)
        pdf = output_dir / f"{input_path.stem}.pdf"
        staged_pdf = output_dir / f".{input_path.stem}.pdf.tmp"
        shutil.copy2(converted, staged_pdf)
        staged_pdf.replace(pdf)
    pages = render_pdf_pages(pdf, output_dir, args.dpi) if args.render_pages else []
    if args.mark_pages_inspected and not args.word_manifest:
        raise ValueError("--mark-pages-inspected requires --word-manifest")
    if args.word_manifest:
        if input_path.suffix.lower() not in {".doc", ".docx", ".docm", ".dot", ".dotx", ".odt"}:
            raise ValueError("--word-manifest can only be used with a Word document")
        if not pages:
            raise ValueError("--word-manifest requires --render-pages")
        update_word_manifest(
            Path(args.word_manifest).expanduser().resolve(),
            output_dir,
            pdf,
            pages,
            args.mark_pages_inspected,
        )
    print(f"LibreOffice: {resolve_soffice()}")
    print(f"PDF: {pdf}")
    if pages:
        print(f"Pages rendered: {len(pages)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
