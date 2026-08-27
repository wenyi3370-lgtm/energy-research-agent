# LibreOffice Rendering Contract

Use this contract for DOCX/PPTX/XLSX conversion or render QA in the workflow.

## Required command

Run the Skill-owned converter instead of calling `soffice --convert-to` directly:

```text
python scripts/libreoffice_render.py <office-file> --output-dir <qa-dir> --render-pages --timeout-seconds 120
```

The script provides:

- a unique LibreOffice profile for every run;
- a standards-compliant `file:///C:/...` UserInstallation URI on Windows;
- explicit Writer/Impress/Calc PDF export filters;
- a 120-second default timeout;
- process-tree cleanup after timeout;
- PDF existence/size validation;
- optional PDF-to-PNG page rendering with PyMuPDF, without a Poppler dependency.

## Rendering dependency

Install PyMuPDF in the runtime used to execute the Skill:

```text
python -m pip install PyMuPDF
```

The renderer imports the modern `pymupdf` module and writes `page-<number>.png` atomically after every PDF page has rendered successfully.

## Diagnosis and recovery

1. Confirm LibreOffice exists with `soffice --headless --version` or set `SOFFICE_PATH` to `soffice.com`/`soffice`.
2. Run the Skill-owned converter with an ASCII-path copy of the input when diagnosing path/encoding issues.
3. Treat a conversion as successful only when the PDF is non-empty; for render QA, require all expected page PNGs.
4. If the command times out, confirm the converter removed only the process tree it launched, then retry once with a fresh output directory.
5. If conversion still fails, retain stdout/stderr, inspect the Office package, fonts, images, fields, and unsupported objects, and use Word/PowerPoint native export only as an explicitly recorded fallback.

Do not reuse LibreOffice's default user profile for automated runs. Do not run unbounded `soffice` commands, and do not use `file://C:\...` as the profile URI on Windows.
