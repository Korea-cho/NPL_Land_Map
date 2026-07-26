# 다중 지번 지적도 조회 (Streamlit 버전)

네이버 지도 / 카카오맵을 선택해서 지번(필지)을 등록하고 지적편집도와 함께 확인하는 도구입니다.
자동차 이동거리·시간 계산은 항상 네이버 Directions 15로 처리됩니다.

## 1. 폴더 구조

```
NPL_Land_Map/
├── app.py
├── requirements.txt
├── .gitignore
└── .streamlit/
    └── secrets.toml.example   # 실제 배포 시엔 이 파일 대신 Streamlit Cloud의 Secrets 설정에 값을 입력
```

## 2. 로컬에서 테스트하기

```bash
pip install -r requirements.txt

# secrets.toml.example을 복사해서 secrets.toml 만들고 실제 값 채우기
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# (편집기로 열어서 실제 비밀번호/키 입력)

streamlit run app.py
```

## 3. GitHub에 올리기

`secrets.toml`은 `.gitignore`에 이미 등록되어 있어 실수로라도 커밋되지 않습니다.
`secrets.toml.example`만 커밋해서, 나중에 다른 사람(또는 미래의 본인)이 어떤 값을 채워야 하는지 알 수 있게 해둔 것입니다.

```bash
git add .
git commit -m "Streamlit 버전으로 전환 (네이버/카카오 선택, 보안 강화)"
git push
```

## 4. Streamlit Community Cloud에 배포하기

1. https://share.streamlit.io 접속 후 GitHub 계정으로 로그인
2. "New app" → 이 저장소(`Korea-cho/NPL_Land_Map`) 선택, `app.py`를 메인 파일로 지정
3. 배포 화면의 **"Secrets"** 설정란에 아래 내용을 실제 값으로 채워서 입력 (여기 입력한 값은 서버에만 저장되고 브라우저로 노출되지 않습니다)

```toml
APP_PASSWORD = "실제 비밀번호"

NAVER_CLIENT_ID = "실제 네이버 Client ID"
NAVER_CLIENT_SECRET = "실제 네이버 Client Secret"

KAKAO_JS_KEY = "실제 카카오 JavaScript 키"
KAKAO_REST_KEY = "실제 카카오 REST API 키"
```

4. Deploy 클릭

## 5. 보안 원칙 요약

- 이 앱은 화면을 서버(Streamlit)에서 그려서 브라우저로 전달하는 구조라, 비밀번호와 네이버 Client Secret / 카카오 REST API 키는 **서버 쪽 코드에서만** 사용되고 브라우저로 절대 전송되지 않습니다.
- 반면 네이버 Client ID와 카카오 JavaScript 키는 지도 SDK가 브라우저에서 직접 렌더링하기 위해 필요한 값이라 소스에 노출되는 게 원래 정상이며, 문제 없는 값입니다.
- `secrets.toml` 파일은 절대 GitHub에 올리지 마세요 (`.gitignore`에 이미 등록되어 있습니다).

## 6. 주요 기능

- 지도 서비스 선택: 네이버 지도 / 카카오맵 (지적편집도 오버레이 포함)
- 지번 주소 일괄 등록 (줄바꿈으로 여러 개 입력)
- 좌표 입력 → 역지오코딩으로 옆 필지 자동 등록
- 등록된 지번별 도형/색상 커스터마이징, 개별 삭제
- 2개 지번 선택 → 네이버 Directions 15로 자동차 이동거리/시간 계산
- 등록된 지번 데이터는 새로고침 시 항상 초기화 (세션 동안만 유지)
