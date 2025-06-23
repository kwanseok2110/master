import urllib.request
from bs4 import BeautifulSoup

data = urllib.request.urlopen('http://comic.naver.com/webtoon/list.nhn?titleId=20853&weekday=fri')
soup = BeautifulSoup(data, 'html.parser')

cartoons = soup.find_all('td', attrs={'class':'title'})

f = open("c:\\work\\webtoon.txt", "wt", encoding="utf-8")
for item in cartoons:
    title = item.find('a').text.strip()
    print(title)
    f.write(title + "\n")

f.close() 

