f = open("DemoFile.txt", "wt", encoding="utf-8")
f.write("This is a demo file.\n")
f.close()

f = open("DemoFile.txt", "rt", encoding="utf-8")
print(f.read())
f.close()