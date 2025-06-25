# 이미지 파일 일괄 넘버링 리네이머 (복사본을 rename 폴더에 저장)
import os
import shutil
from tkinter import Tk, filedialog

def rename_images_in_folder():
    # 폴더 선택 창 띄우기
    root = Tk()
    root.withdraw()
    folder = filedialog.askdirectory(title="이미지 폴더 선택")
    if not folder:
        print("폴더를 선택하지 않았습니다.")
        return

    # 이미지 확장자 목록
    image_exts = ('.jpg', '.jpeg', '.png', '.gif', '.bmp')
    files = [
        f for f in os.listdir(folder)
        if f.lower().endswith(image_exts) and os.path.isfile(os.path.join(folder, f))
    ]
    files.sort()

    # rename 하위 폴더 생성
    rename_folder = os.path.join(folder, "rename")
    os.makedirs(rename_folder, exist_ok=True)

    # 파일 복사 및 이름 변경
    for idx, filename in enumerate(files, 1):
        src_path = os.path.join(folder, filename)
        ext = os.path.splitext(filename)[1]
        new_name = f"{idx}{ext}"
        dst_path = os.path.join(rename_folder, new_name)
        shutil.copy2(src_path, dst_path)
        print(f"{filename} → rename/{new_name}")

    print("복사 및 이름 변경 완료!")

if __name__ == "__main__":
    rename_images_in_folder()

#전체 주석처리 : CTRL + /

