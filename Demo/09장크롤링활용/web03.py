import urllib.request
from bs4 import BeautifulSoup

f = open("c:\\work\\webtoon.txt", "wt", encoding="utf-8")
#페이징처리 추가 
for i in range(1,6):
    url = 'https://comic.naver.com/webtoon/list?titleId=20853&weekday=fri&page=' + str(i)
    print(url)
    data = urllib.request.urlopen(url)
    soup = BeautifulSoup(data, 'html.parser')

    cartoons = soup.find_all('td', attrs={'class':'title'})

    for item in cartoons:
        title = item.find('a').text.strip()
        print(title)
        f.write(title + "\n")

f.close() 

