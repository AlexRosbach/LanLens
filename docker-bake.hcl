variable "LANLENS_APP_VERSION" {
  default = "1.6.0"
}

variable "LANLENS_BUILD_CODE" {
  default = "dev"
}

variable "LANLENS_BUILD_COMMIT" {
  default = "unknown"
}

variable "LANLENS_BUILD_BRANCH" {
  default = "unknown"
}

variable "LANLENS_BUILD_CREATED" {
  default = "unknown"
}

group "default" {
  targets = ["lanlens"]
}

target "lanlens" {
  context = "."
  dockerfile = "Dockerfile"
  platforms = ["linux/amd64", "linux/arm64"]
  tags = ["alexrosbach/lanlens:dev"]
  args = {
    LANLENS_APP_VERSION = LANLENS_APP_VERSION
    LANLENS_BUILD_CODE = LANLENS_BUILD_CODE
    LANLENS_BUILD_COMMIT = LANLENS_BUILD_COMMIT
    LANLENS_BUILD_BRANCH = LANLENS_BUILD_BRANCH
    LANLENS_BUILD_CREATED = LANLENS_BUILD_CREATED
  }
}
