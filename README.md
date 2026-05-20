# Local AI Assistant

브라우저에서 실행되는 간단한 AI Assistant입니다. 앱은 내 PC에서 실행되고, 모델 연결은 두 가지 중 하나를 선택할 수 있습니다.

- `OpenAI`: 앱은 로컬에서 실행, 추론은 OpenAI API 사용
- `Ollama`: 앱과 모델 모두 로컬에서 실행 가능

## 1. 실행 방법

PowerShell에서 아래 명령을 실행합니다.

```powershell
cd C:\Users\User\Documents\AIAssistantLocal
Copy-Item .env.example .env
notepad .env
python .\app.py
```

실행 후 브라우저에서 `http://127.0.0.1:8000` 으로 접속합니다.

`start_local.ps1`로 더 간단히 실행할 수도 있습니다.

```powershell
.\start_local.ps1
```

## 2. OpenAI로 연결

`.env` 파일을 이렇게 설정합니다.

```env
AI_PROVIDER=openai
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-5.4-mini
```

이 앱은 OpenAI `Responses API` 방식으로 호출합니다.
공식 문서: <https://platform.openai.com/docs/api-reference/responses>

## 3. Ollama로 연결

먼저 Ollama를 설치하고 모델을 내려받습니다.

```powershell
ollama pull llama3.2
```

그 다음 `.env`를 이렇게 설정합니다.

```env
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.2
```

이 앱은 Ollama `POST /api/chat` 방식으로 호출합니다.
공식 문서: <https://docs.ollama.com/api/chat>

## 4. 현재 구성의 장점

- Python 표준 라이브러리만 사용해서 추가 설치가 거의 필요 없습니다.
- OpenAI와 Ollama를 환경 변수만 바꿔서 전환할 수 있습니다.
- 브라우저 UI가 같이 포함되어 있어서 바로 테스트할 수 있습니다.

## 5. 다음 확장 아이디어

- 대화 내용 파일 저장
- 음성 입력/출력
- 문서 업로드 후 질문
- 사내 API 호출용 도구 기능 추가
