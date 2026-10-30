Set WshShell = CreateObject("WScript.Shell")
WshShell.Environment("Process")("PYTHONUTF8") = "1"
WshShell.Run "C:\Users\Gamas\AppData\Local\Programs\Python\Python314\python.exe C:\discord-bot\discord-bot\main.py", 0, False
Set WshShell = Nothing
