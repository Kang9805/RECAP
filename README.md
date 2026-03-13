# RECAP - Receipt OCR

영수증 이미지에서 텍스트를 자동으로 추출하고 항목을 분류하는 Django 기반 웹 애플리케이션입니다.

## 기능

- **영수증 업로드**: 이미지 형식의 영수증 파일 업로드
- **자동 OCR**: Tesseract를 사용한 텍스트 추출
- **항목 관리**: 영수증 항목(상품명, 수량, 가격) 저장 및 조회
- **관리자 인터페이스**: Django Admin을 통한 데이터 관리

## 기술 스택

- **Backend**: Django 6.0.2
- **Database**: SQLite
- **OCR**: Tesseract (pytesseract)
- **Image Processing**: Pillow

## 설치

### 요구사항

- Python 3.8 이상
- pip

### 1. 저장소 클론

```bash
git clone https://github.com/Kang9805/RECAP.git
cd RECAP
```

### 2. 가상 환경 생성 및 활성화

```bash
# macOS/Linux
python -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

### 3. 의존성 설치

```bash
pip install -r requirements.txt
```

### 4. Tesseract OCR 설치 (선택사항)

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# Windows
# https://github.com/UB-Mannheim/tesseract/wiki 참고
```

## 실행

### 1. 마이그레이션 적용

```bash
python manage.py migrate
```

### 2. 슈퍼유저 생성 (선택사항)

```bash
python manage.py createsuperuser
```

### 3. 개발 서버 시작

```bash
python manage.py runserver
```

### 3-1. Celery Worker/Beat 시작 (비동기 OCR + 정기 stuck 정리)

```bash
# worker
celery -A config worker --loglevel=info

# beat (주기적으로 mark_stuck_receipts_task 실행)
celery -A config beat --loglevel=info
```

Docker Compose를 사용한다면 아래처럼 `web`, `worker`, `beat`를 함께 실행할 수 있습니다.

```bash
docker compose up --build
```

서버는 `http://127.0.0.1:8000/` 에서 실행됩니다.

### 4. Admin 접근

관리자 페이지: `http://127.0.0.1:8000/admin/`

## 프로젝트 구조

```
recap/
├── config/              # 프로젝트 설정
│   ├── settings.py      # Django 설정
│   ├── urls.py          # URL 라우팅
│   ├── asgi.py          # ASGI 설정
│   └── wsgi.py          # WSGI 설정
├── scanner/             # 영수증 처리 앱
│   ├── models.py        # 데이터 모델
│   ├── views.py         # 뷰 함수
│   ├── admin.py         # Admin 설정
│   ├── apps.py          # 앱 설정
│   ├── tests.py         # 테스트 코드
│   ├── services/        # 비즈니스 로직
│   │   └── ocr.py       # OCR 기능
│   └── migrations/      # 데이터베이스 마이그레이션
├── manage.py            # Django 관리 유틸리티
└── requirements.txt     # Python 패키지 의존성
```

## 데이터 모델

### Receipt (영수증)

- `image`: 영수증 이미지 파일
- `extracted_text`: OCR로 추출한 텍스트
- `uploaded_at`: 업로드 시간

### ReceiptItem (영수증 항목)

- `receipt`: 소속 영수증 (ForeignKey)
- `name`: 상품명
- `quantity`: 수량
- `unit_price`: 단가

## 라이선스

MIT License

## 운영 설정 환경변수

- `OCR_PROCESSING_STUCK_MINUTES`: processing 상태 최대 허용 시간(분)
- `CELERY_BEAT_STUCK_CHECK_MINUTES`: stuck 정리 task 실행 주기(분)
- `OCR_RETRYABLE_ERROR_CODES`: 일괄 재처리 허용 실패 코드 목록 (쉼표 구분)

## 운영 백업/복구

백업 스크립트는 `scripts/ops/backup.sh` 입니다.

```bash
# 프로젝트 루트에서 실행
./scripts/ops/backup.sh
```

생성 결과:
- DB 백업: `backups/db/recap_db_YYYYMMDD_HHMMSS.sql.gz`
- 미디어 백업: `backups/media/recap_media_YYYYMMDD_HHMMSS.tar.gz`

옵션 환경변수:
- `RETENTION_DAYS` (기본 7): 보관일 지난 백업 자동 삭제
- `BACKUP_ROOT` (기본 `./backups`): 백업 저장 경로 변경

```bash
RETENTION_DAYS=14 ./scripts/ops/backup.sh
```

DB 복구 스크립트는 `scripts/ops/restore_db.sh` 입니다.

```bash
./scripts/ops/restore_db.sh backups/db/recap_db_YYYYMMDD_HHMMSS.sql.gz
```

### crontab 등록 예시 (VM)

매일 새벽 3시에 백업:

```bash
crontab -e
```

```cron
0 3 * * * cd /home/groupip98/RECAP && ./scripts/ops/backup.sh >> /home/groupip98/RECAP/backups/backup.log 2>&1
```
