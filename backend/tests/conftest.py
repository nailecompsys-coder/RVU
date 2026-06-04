import os

os.environ.setdefault("DATABASE_URL", "postgresql://rvu_test:rvu_test@127.0.0.1:5432/rvu_test")
os.environ.setdefault("SECRET_KEY", "rvu-test-secret")
