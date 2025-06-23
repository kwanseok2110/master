# DemoIndexing.py

x = 100
y = 3.14
strA = "python"
strB = "파이썬은 강력해"

print(dir())
print(len(strA))
print(len(strB))

#슬라이싱
print(strA[0])      #0부터 1개
print(strA[0:2])    #0부터 2개
print(strA[:4])     #앞에서 4개
print(strA[-3:])    #뒤에서 3개

#다중 라인
strMulti = """나는
다중라인을
연습하고 있어"""
print(strMulti)

#리스트 연습 (Linked List를 그냥 사용 가능)
colors = ["red", "greed", "blue"]
print(colors)
colors.append("white") #뒤에 추가
print(colors)
colors.insert(0, "black") #Index에 추가
print(colors)
print(type(colors))

#삭제
colors.remove("red")
print(colors)

#====================
#SET : 중복을 스스로 제거
a = {1,2,3,3}
b = {3,4,4,5} 
c = a.union(b)
d = a.difference(b)
print(a);
print(b);
print(c); #교집합
print(d); #차집합

#튜플 : 함수에서 하나 이상의 값을 리턴하는 경우
def calc(a,b):
    return a+b, a*b

result = calc(5,6)
print(result)

#문자열 변수 출력
print("id:%s, name:%s" %("yang", "양관석"))
