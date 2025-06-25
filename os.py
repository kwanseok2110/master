import os

print("운영체제 : ", os.name)
print("환경변수 : ", os.environ)

#특정 폴더의 파일리스트
import glob

result = glob.glob("F:\Work_Python\*.py")
for item in result:
    print(item)