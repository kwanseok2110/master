import re

def is_valid_email(email):
    # 간단한 이메일 정규표현식
    pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$'
    return re.match(pattern, email) is not None

# 샘플 이메일 10개
emails = [
    "test@example.com",
    "user.name@domain.co.kr",
    "user_name@domain.com",
    "username@domain",
    "username@.com",
    "user@domain.c",
    "user@domain.company",
    "user@domain..com",
    "user@domain.com.",
    "user@domain.com"
]

for email in emails:
    result = "유효함" if is_valid_email(email) else "유효하지 않음"
    print(f"{email} → {result}")

