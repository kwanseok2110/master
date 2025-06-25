from bs4 import BeautifulSoup

page = open("test01.html", "rt", encoding="utf-8").read()
soup = BeautifulSoup(page, "html.parser")

#전체 보기
#print(soup.prettify())

#태그 검색
#print(soup.find("p"))  #첫번째 p 태그

#조건 : <p class="outer-text">
#print(soup.find_all("p", class_="outer-text"))  #class 속성값이 outer-text인 p 태그

#조건검색 : attrs속성 dict형식
#print(soup.find_all(attrs={"class": "outer-text"}))  #class 속성값이 outer-text인 모든 태그

#태그 내부의 문자열: .txet 속성
for tag in soup.find_all("p"):
    title = tag.text.strip()  #공백제거
    title = title.replace("\n", "")  #줄바꿈 제거
    print(title)
