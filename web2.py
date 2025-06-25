#<span class="fa fa-pencil button_icon"></span>

from bs4 import BeautifulSoup

import urllib.request

url = "https://www.clien.net/service/board/sold"

file = open("clien.txt", "wt", encoding="utf-8")
data = urllib.request.urlopen(url).read()
soup = BeautifulSoup(data, "html.parser")
list = soup.find_all("span", attrs={"data-role": "list-title-text"})
for item in list:
    title = item.text.strip()  # 공백제거
    title = title.replace("\n", "")  # 줄바꿈 제거
    print(title)
    file.write(title + "\n")  # 파일에 저장
file.close()


