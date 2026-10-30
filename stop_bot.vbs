Set objWMI = GetObject("winmgmts:\\.\root\cimv2")
Set colProcesses = objWMI.ExecQuery("SELECT * FROM Win32_Process WHERE Name='python.exe'")
Dim count : count = 0
For Each proc In colProcesses
    If InStr(LCase(proc.CommandLine), "main.py") > 0 Then
        proc.Terminate()
        count = count + 1
    End If
Next
If count > 0 Then
    MsgBox "Bot detenido (" & count & " proceso/s terminado/s).", 64, "Discord Bot"
Else
    MsgBox "El bot no estaba corriendo.", 48, "Discord Bot"
End If
