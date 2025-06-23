# web1.py
from bs4 import BeautifulSoup

page = open("c:\\work\\test01.html", "rt", 
    encoding="utf-8").read()
soup = BeautifulSoup(page, "html.parser")
#print(soup.prettify())

# print("---전체 <p>태그를 검색---")
# print( soup.find_all("p") ) 

# print("---하나를 검색하는 경우--")
# print( soup.find("p") )
# print("---조건이 있는 경우---")
# print( soup.find_all("p", class_="outer-text") )
# print("---attrs속성을 사용하는경우---")
# print( soup.find_all("p", attrs={"class":"outer-text"}))

# print("---id를 지정한다---")
# print( soup.find_all(id="first") )

print("---검색한 요소에서 컨텐츠만 출력한다.---")
for item in soup.find_all("p"):
    title = item.text.strip()
    title = title.replace("\n","")
    print(title)

