import os


APP_VERSION = "1.5.3"
BUILD_CODE = os.getenv("LANLENS_BUILD_CODE", "dev")
BUILD_COMMIT = os.getenv("LANLENS_BUILD_COMMIT", "unknown")
BUILD_BRANCH = os.getenv("LANLENS_BUILD_BRANCH", "unknown")
BUILD_CREATED = os.getenv("LANLENS_BUILD_CREATED", "unknown")
