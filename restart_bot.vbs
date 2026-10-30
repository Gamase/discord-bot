Set objWMI = GetObject("winmgmts:\\.\root\cimv2")
Set colProcesses = objWMI.ExecQuery("SELECT * FROM Win32_Process WHERE Name='python.exe'")
For Each proc In colProcesses
    If InStr(LCase(proc.CommandLine), "main.py") > 0 Then
        proc.Terminate()
    End If
Next
WScript.Sleep 1500
Set WshShell = CreateObject("WScript.Shell")
WshShell.Environment("Process")("PYTHONUTF8") = "1"
WshShell.Run "C:\Users\Gamas\AppData\Local\Programs\Python\Python314\python.exe C:\discord-bot\discord-bot\main.py", 0, False
Set WshShell = Nothing
MsgBox "Bot reiniciado correctamente.", 64, "Discord Bot"
