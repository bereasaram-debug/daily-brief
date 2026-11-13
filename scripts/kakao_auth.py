#!/usr/bin/env python3
"""카카오 토큰 최초 발급 (PC에서 1회 실행)

사용법:  python scripts/kakao_auth.py
- REST API 키와 클라이언트 시크릿을 입력합니다(화면에 표시되지 않음).
- 브라우저에서 카카오 로그인·동의를 마치면, GitHub Secrets에 등록할 값 3개를 화면에 한 번 출력합니다.
- 어떤 값도 파일로 저장하지 않습니다.
- 표준 라이브러리만 사용하므로 별도 설치가 필요 없습니다.
"""
import getpass
import http.server
import json
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

PORT = 8765
REDIRECT_URI = f"http://localhost:{PORT}/callback"
AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"

result = {}
done = threading.Event()


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        result["code"] = params.get("code", [None])[0]
        result["state"] = params.get("state", [None])[0]
        result["error"] = params.get("error_description", params.get("error", [None]))[0]
        ok = result["code"] is not None
        body = ("<h2>인증 완료. 이 창을 닫고 터미널로 돌아가세요.</h2>" if ok
                else "<h2>인증 실패. 터미널 메시지를 확인하세요.</h2>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))
        done.set()

    def log_message(self, *args):  # 요청 로그(인가 코드 포함) 출력 안 함
        pass


def main():
    print("=== 카카오 토큰 최초 발급 ===")
    print("입력하는 값은 화면에 보이지 않습니다. 붙여넣고 Enter를 누르세요.\n")
    rest_key = getpass.getpass("REST API 키: ").strip()
    client_secret = getpass.getpass("클라이언트 시크릿(카카오 로그인용): ").strip()
    if not rest_key or not client_secret:
        sys.exit("REST API 키와 클라이언트 시크릿이 모두 필요합니다.")

    state = secrets.token_urlsafe(16)
    query = urllib.parse.urlencode({
        "client_id": rest_key,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "talk_message",
        "state": state,
    })
    auth_url = f"{AUTHORIZE_URL}?{query}"

    try:
        server = http.server.HTTPServer(("localhost", PORT), CallbackHandler)
    except OSError:
        sys.exit(f"포트 {PORT}을 이미 다른 프로그램이 쓰고 있습니다. 해당 프로그램을 닫고 다시 실행하세요.")
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print("\n브라우저에서 카카오 로그인·동의 화면을 엽니다.")
    print("브라우저가 열리지 않으면 아래 주소를 직접 복사해 여세요:\n")
    print(auth_url + "\n")
    webbrowser.open(auth_url)

    if not done.wait(timeout=300):
        server.shutdown()
        sys.exit("5분 안에 인증이 완료되지 않았습니다. 다시 실행하세요.")
    server.shutdown()

    if result.get("state") != state:
        sys.exit("보안 확인(state) 값이 일치하지 않습니다. 다시 실행하세요.")
    if not result.get("code"):
        sys.exit(f"인가 코드를 받지 못했습니다: {result.get('error')}")

    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": rest_key,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "code": result["code"],
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            token = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        sys.exit(f"토큰 발급 실패 (HTTP {e.code}): {detail}\n"
                 "리다이렉트 URI, 클라이언트 시크릿 사용 설정, 동의항목을 확인하세요.")

    refresh_token = token.get("refresh_token")
    if not refresh_token:
        sys.exit("응답에 refresh_token이 없습니다. 카카오 로그인 설정을 확인하세요.")
    if "talk_message" not in (token.get("scope") or ""):
        print("\n[주의] 'talk_message' 권한이 응답에 없습니다. 동의항목에서 "
              "'카카오톡 메시지 전송'을 켜고, 로그인 시 동의했는지 확인하세요.")

    print("\n" + "=" * 60)
    print("아래 3개를 GitHub 저장소 Settings → Secrets and variables → Actions →")
    print("New repository secret 에 각각 등록하세요. (이 화면을 닫으면 다시 볼 수 없습니다)")
    print("=" * 60)
    print(f"KAKAO_REST_KEY      = {rest_key}")
    print(f"KAKAO_CLIENT_SECRET = {client_secret}")
    print(f"KAKAO_REFRESH_TOKEN = {refresh_token}")
    print("=" * 60)
    print("등록 후 이 터미널 창의 내용은 지워 주세요(cls 또는 창 닫기).")


if __name__ == "__main__":
    main()
