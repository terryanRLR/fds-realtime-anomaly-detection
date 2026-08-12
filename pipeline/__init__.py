"""pipeline — FDS 공용 로직 패키지.

여기에 로직을 두지 않는다. 단 하나, **콘솔 인코딩 보정**만 한다.

왜 이 파일에 있는가
  이 패키지의 모듈들은 진행 상황을 `━ ═ ─ ✅ ❌ ★ —` 같은 문자로 출력한다.
  그런데 한국어 Windows 의 기본 콘솔 코드페이지는 **cp949** 라서 이 문자들을
  인코딩할 수 없다. 그래서 다음 명령이 첫 print 에서 즉사했다:

      python -m pipeline.selftest_preprocessor
      UnicodeEncodeError: 'cp949' codec can't encode character '—'

  러너(`selftest_all`)를 통해 돌리면 자식 프로세스에 `PYTHONIOENCODING=utf-8`
  이 넘어가서 괜찮았다 — 즉 **개별 실행 경로만** 깨져 있었고, 자가검증 12종을
  하나씩 돌려 보려는 사람이 그 벽을 만났다.

  모듈마다 같은 4줄을 넣는 대신 패키지 진입점 한 곳에서 처리한다.
  `python -m pipeline.<무엇이든>` 은 항상 이 파일을 먼저 거친다.

무해하게 만드는 조건
  · 이미 출력 가능한 인코딩(UTF-8 등)이면 **아무것도 하지 않는다.**
  · 실패해도 조용히 넘어간다 — 인코딩 보정 때문에 앱이 죽으면 안 된다.
  · `errors="replace"` 를 쓰지 않는다. 글자가 깨진 채 통과하면 로그를 믿을 수
    없게 되므로, UTF-8 로 바꿀 수 있을 때만 바꾸고 아니면 원래대로 둔다.
"""

_PROBE = "━✅—"          # 이 패키지가 실제로 출력하는 문자들의 대표 표본


def _fix_console_encoding() -> None:
    import sys
    for stream in (sys.stdout, sys.stderr):
        if stream is None:                      # pythonw 등
            continue
        enc = getattr(stream, "encoding", None)
        if enc:
            try:
                _PROBE.encode(enc)
                continue                        # 이미 출력 가능 → 손대지 않는다
            except (UnicodeEncodeError, LookupError):
                pass
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:                       # 리다이렉트된 스트림 등
            pass


_fix_console_encoding()
