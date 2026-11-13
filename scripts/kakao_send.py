#!/usr/bin/env python3
"""카카오톡 '나에게 보내기' 발송 (GitHub Actions에서 실행)

환경변수
  KAKAO_REST_KEY, KAKAO_CLIENT_SECRET, KAKAO_REFRESH_TOKEN : GitHub Secrets
  SUMMARY_FILE : 보낼 요약 파일 경로 (비우면 테스트 메시지 발송)
  PAGE_URL     : [전문 보기] 버튼이 열 주소
  GITHUB_OUTPUT: Actions가 자동 제공 (token_updated=true 출력용)

토큰 처리
  1) 저장소에 kakao_token.enc 가 있으면 KAKAO_CLIENT_SECRET으로 복호화한 토큰을 먼저 사용
  2) 실패하면 Secrets의 KAKAO_REFRESH_TOKEN 사용
  3) 갱신 응답에 새 refresh_token이 있으면 암호화해 kakao_token.enc 로 저장
     (커밋은 워크플로가 수행). 토큰은 ::add-mask:: 로 로그에서 가림.
"""
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
ENC_FILE = "kakao_token.enc"
MAX_TEXT = 200  # 카카오 텍스트 템플릿 최대 길이


def mask(value):
    if value:
        print(f"::add-mask::{value}", flush=True)


def post(url, data, headers=None):
    body = urllib.parse.urlencode(data).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}


def openssl(args, input_text):
    return subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-a", "-A",
         "-pass", "env:KAKAO_CLIENT_SECRET", *args],
        input=input_text, capture_output=True, text=True)


def decrypt_saved_token():
    if not os.path.exists(ENC_FILE):
        return None
    with open(ENC_FILE, encoding="utf-8") as f:
        r = openssl(["-d"], f.read().strip())
    if r.returncode != 0 or not r.stdout.strip():
        print("::warning::kakao_token.enc 복호화 실패. Secrets 토큰을 사용합니다.")
        return None
    return r.stdout.strip()


def save_new_token(token):
    r = openssl([], token)
    if r.returncode != 0:
        print("::error::새 refresh token 암호화 실패")
        return False
    with open(ENC_FILE, "w", encoding="utf-8") as f:
        f.write(r.stdout.strip() + "\n")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write("token_updated=true\n")
    print("새 refresh token을 암호화해 kakao_token.enc 에 저장했습니다.")
    return True


def get_access_token(rest_key, client_secret):
    candidates = []
    saved = decrypt_saved_token()
    if saved:
        mask(saved)
        candidates.append(("kakao_token.enc", saved))
    secret_token = os.environ.get("KAKAO_REFRESH_TOKEN", "").strip()
    if secret_token and secret_token != saved:
        candidates.append(("Secrets", secret_token))
    if not candidates:
        sys.exit("::error::사용할 refresh token이 없습니다. KAKAO_REFRESH_TOKEN Secret을 확인하세요.")

    for source, refresh in candidates:
        status, res = post(TOKEN_URL, {
            "grant_type": "refresh_token",
            "client_id": rest_key,
            "client_secret": client_secret,
            "refresh_token": refresh,
        })
        if status == 200 and res.get("access_token"):
            mask(res["access_token"])
            new_refresh = res.get("refresh_token")
            if new_refresh:
                mask(new_refresh)
                save_new_token(new_refresh)
            print(f"access token 발급 성공 (refresh token 출처: {source})")
            return res["access_token"]
        print(f"::warning::{source} 토큰으로 갱신 실패 (HTTP {status}, "
              f"{res.get('error')}: {res.get('error_description')})")
    sys.exit("::error::access token 발급 실패. kakao_auth.py로 토큰을 다시 발급해 "
             "KAKAO_REFRESH_TOKEN Secret을 교체하고, kakao_token.enc 파일을 삭제하세요.")


def main():
    rest_key = os.environ.get("KAKAO_REST_KEY", "").strip()
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET", "").strip()
    if not rest_key or not client_secret:
        sys.exit("::error::KAKAO_REST_KEY / KAKAO_CLIENT_SECRET Secret이 없습니다.")
    mask(rest_key)
    mask(client_secret)

    page_url = os.environ.get("PAGE_URL", "").strip()
    summary_file = os.environ.get("SUMMARY_FILE", "").strip()
    if summary_file:
        with open(summary_file, encoding="utf-8") as f:
            text = f.read().strip()
    else:
        text = "[데일리 브리핑] 테스트 발송입니다. 이 메시지가 보이면 카카오 연동 성공."
    if not text:
        sys.exit("::error::요약 파일이 비어 있습니다.")
    if len(text) > MAX_TEXT:
        print(f"::warning::요약이 {len(text)}자라 {MAX_TEXT}자로 잘라 보냅니다.")
        text = text[:MAX_TEXT - 1] + "…"

    template = {
        "object_type": "text",
        "text": text,
        "link": {"web_url": page_url, "mobile_web_url": page_url},
        "button_title": "전문 보기",
    }

    access_token = get_access_token(rest_key, client_secret)
    status, res = post(
        SEND_URL,
        {"template_object": json.dumps(template, ensure_ascii=False)},
        {"Authorization": f"Bearer {access_token}"})
    if status == 200 and res.get("result_code") == 0:
        print("카카오톡 발송 성공")
    else:
        sys.exit(f"::error::카카오톡 발송 실패 (HTTP {status}): {res}")


if __name__ == "__main__":
    main()
