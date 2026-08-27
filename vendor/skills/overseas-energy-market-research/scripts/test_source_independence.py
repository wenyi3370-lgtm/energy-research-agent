# -*- coding: utf-8 -*-
"""FIX-04 regression: root-domain / source independence with full PSL rules.

Acceptance (per the reliability fix spec):
- a.com.es vs b.com.es -> two INDEPENDENT registrable domains
- energia.gob.es vs industria.gob.es -> two independent government domains
- co.uk / com.cn / com.au / com.es / gob.es / co.za / com.ng / co.ke /
  com.br / com.mx / co.jp / co.kr all resolve to registrable domains
- ordinary .com / .org hosts collapse to the registrable domain
- IP hosts pass through unchanged

Self-contained, offline, deterministic. Exit 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_independence import root_domain_from_url  # noqa: E402

CASES: list[tuple[str, str]] = [
    # (input URL/host, expected registrable domain)
    ("https://a.com.es/", "a.com.es"),
    ("https://b.com.es/", "b.com.es"),
    ("https://energia.gob.es/", "energia.gob.es"),
    ("https://industria.gob.es/", "industria.gob.es"),
    ("https://www.example.co.uk/", "example.co.uk"),
    ("http://shop.example.com.cn/", "example.com.cn"),
    ("https://www.tesla.com.au/", "tesla.com.au"),
    ("https://pv-magazine.co.za/", "pv-magazine.co.za"),
    ("https://nep.ng/", "nep.ng"),
    ("https://data.go.ke/", "data.go.ke"),
    ("https://www.portalsolar.com.br/", "portalsolar.com.br"),
    ("https://www.cfe.com.mx/", "cfe.com.mx"),
    ("https://www.meti.co.jp/", "meti.co.jp"),
    ("https://www.kesco.co.kr/", "kesco.co.kr"),
    ("https://www.example.com/", "example.com"),
    ("https://www.example.org/", "example.org"),
    ("https://gov.cn/", "gov.cn"),
    ("https://sub.deep.gov.cn/", "deep.gov.cn"),
    ("https://192.168.1.1/", "192.168.1.1"),
    ("", ""),
    # FIX round-2 P2-8: wildcard / exception PSL semantics (full frozen list)
    ("https://www.cookisland.ck/", "cookisland.ck"),   # *.ck wildcard
    ("https://a.cookisland.ck/", "a.cookisland.ck"),  # *.ck: cookisland.ck is the suffix
    ("https://www.www.ck/", "www.ck"),                 # !www.ck exception
    ("https://www.ck/", "www.ck"),
    # more global markets (full PSL)
    ("https://x.com.ng/", "x.com.ng"),
    ("https://x.gov.ng/", "x.gov.ng"),
    ("https://x.com.eg/", "x.com.eg"),
    ("https://x.gov.eg/", "x.gov.eg"),
    ("https://x.co.il/", "x.co.il"),
    ("https://x.gov.il/", "x.gov.il"),
    ("https://x.com.pk/", "x.com.pk"),
    ("https://x.com.ua/", "x.com.ua"),
    ("https://x.com.vn/", "x.com.vn"),
    ("https://x.co.th/", "x.co.th"),
    ("https://x.go.th/", "x.go.th"),
    ("https://x.com.kw/", "x.com.kw"),
    ("https://x.com.qa/", "x.com.qa"),
    ("https://x.com.om/", "x.com.om"),
    ("https://x.com.bh/", "x.com.bh"),
    ("https://x.com.jo/", "x.com.jo"),
    ("https://x.com.hk/", "x.com.hk"),
    ("https://x.com.tw/", "x.com.tw"),
    ("https://x.com.sg/", "x.com.sg"),
    ("https://x.com.my/", "x.com.my"),
    ("https://x.com.id/", "com.id"),
    ("https://x.com.ph/", "x.com.ph"),
    ("https://x.com.tr/", "x.com.tr"),
    ("https://x.com.ae/", "com.ae"),
    ("https://x.com.sa/", "x.com.sa"),
    ("https://x.com.in/", "x.com.in"),
    ("https://x.com.bd/", "x.com.bd"),
    ("https://x.com.lk/", "x.com.lk"),
    ("https://x.com.ma/", "com.ma"),
    ("https://x.com.ar/", "x.com.ar"),
    ("https://x.gob.ar/", "x.gob.ar"),
    ("https://x.com.cl/", "com.cl"),
    ("https://x.com.pe/", "x.com.pe"),
    ("https://x.com.co/", "x.com.co"),
    ("https://x.gov.co/", "x.gov.co"),
    ("https://x.com.ec/", "x.com.ec"),
    ("https://x.com.bo/", "x.com.bo"),
    ("https://x.com.py/", "x.com.py"),
    ("https://x.com.uy/", "x.com.uy"),
    ("https://x.com.do/", "x.com.do"),
    ("https://x.com.gt/", "x.com.gt"),
    ("https://x.com.cr/", "com.cr"),
    ("https://x.com.pa/", "x.com.pa"),
    ("https://x.ac.uk/", "x.ac.uk"),
    ("https://x.org.uk/", "x.org.uk"),
    ("https://x.net.cn/", "x.net.cn"),
    ("https://x.org.cn/", "x.org.cn"),
    ("https://x.edu.cn/", "x.edu.cn"),
    ("https://x.ac.jp/", "x.ac.jp"),
    ("https://x.ne.jp/", "x.ne.jp"),
    ("https://x.or.jp/", "x.or.jp"),
    ("https://x.go.jp/", "x.go.jp"),
    ("https://x.go.kr/", "x.go.kr"),
    ("https://x.or.kr/", "x.or.kr"),
    ("https://x.ac.kr/", "x.ac.kr"),
    ("https://x.govt.nz/", "x.govt.nz"),
    ("https://x.co.nz/", "x.co.nz"),
    ("https://x.org.za/", "x.org.za"),
    ("https://x.gov.za/", "x.gov.za"),
    ("https://x.edu.au/", "x.edu.au"),
    ("https://x.org.au/", "x.org.au"),
    ("https://x.net.au/", "x.net.au"),
    ("https://x.gov.au/", "x.gov.au"),
    ("https://x.com.ve/", "x.com.ve"),
    ("https://x.com.mx/", "x.com.mx"),
    ("https://x.com.br/", "x.com.br"),
    # FIX round-3 P1-3/4: deep-domain wildcard / exception semantics
    ("https://y.x.a.ck/", "x.a.ck"),             # *.ck: suffix=a.ck -> registrable=x.a.ck
    ("https://sub.www.ck/", "www.ck"),           # !www.ck exception -> registrable=www.ck
    ("https://z.a.b.kawasaki.jp/", "a.b.kawasaki.jp"),  # *.kawasaki.jp deep
    ("https://x.city.kawasaki.jp/", "city.kawasaki.jp"),  # !city.kawasaki.jp exception
    ("https://www.city.kawasaki.jp/", "city.kawasaki.jp"),
    ("https://a.b.c.example.com/", "example.com"),       # normal exact, multi-level subdomain
    ("https://deep.sub.example.co.uk/", "example.co.uk"),  # multi-label exact suffix
        ("https://some.unknown.tldxyz/", "unknown.tldxyz"),  # default "*" rule
    ("https://x.ck/", "x.ck"),                    # single label under wildcard TLD
    ("https://ck/", "ck"),                        # bare TLD
]


def main() -> int:
    failures: list[str] = []
    for url, expected in CASES:
        got = root_domain_from_url(url)
        if got != expected:
            failures.append("%s -> %r (期望 %r)" % (url, got, expected))
    # 独立性判定：a.com.es 与 b.com.es 必须不同（此前手工表会归一化为 com.es）
    a = root_domain_from_url("https://a.com.es/")
    b = root_domain_from_url("https://b.com.es/")
    if a == b:
        failures.append("a.com.es 与 b.com.es 被错误归一化为同一根域 %r" % a)
    g1 = root_domain_from_url("https://energia.gob.es/")
    g2 = root_domain_from_url("https://industria.gob.es/")
    if g1 == g2:
        failures.append("energia.gob.es 与 industria.gob.es 被错误归一化 %r" % g1)
    if failures:
        print("FIX-04 source-independence regression: FAIL")
        for f in failures:
            print("  -", f)
        return 1
    print("FIX-04 source-independence regression: PASS (%d cases)" % len(CASES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
