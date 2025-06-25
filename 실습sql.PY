import sqlite3
#con =  sqlite3.connect(":memory:")
con =  sqlite3.connect("F:\\Work_Python\\test.db")  #파일로 저장
cur = con.cursor()

#테이블 생성
cur.execute("create table if not exists person " +
            "(id integer primary key autoincrement, name text, phoneNum text);")

#데이터 입력
cur.execute("insert into person (name, phoneNum) values (?, ?);",
       ("홍길동", "010-1234-5678"))

#입력 파라메터 처리: GUI화면에서 별도 입력
name = "전우치"
phoneNum = "010-9876-5432"
cur.execute("insert into person (name, phoneNum) values (?, ?);", (name, phoneNum))

#다중의 레코드를 입력
datalist = (("이순신", "010-1111-2222"),("강감찬", "010-3333-4444"))
cur.executemany("insert into person (name, phoneNum) values (?, ?);", datalist)

con.commit()  #입력한 내용을 저장 ★ 이걸 안하면, 다음로에 DB를 불러올 때 값이 안읽힌다.

#데이터 조회
cur.execute("select * from person;")
for row in cur:
    print(row)

cur.execute("select * from person;")
print("---fetchone()---")
print(cur.fetchone())  #한 레코드만 가져오기

print("---fetchmany(2)---")
print(cur.fetchmany(2))  #2개의 레코드 가져오기

print("---fetchall()---")
print(cur.fetchall())  #모든 레코드 가져오기

