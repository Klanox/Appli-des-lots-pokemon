Option Explicit

Dim shell, http, ready, i
Dim projectPath, operaPath, appUrl, healthUrl

Set shell = CreateObject("WScript.Shell")

projectPath = "C:\Users\User\Desktop\Appli des lots pokemon"
operaPath = "C:\Users\User\AppData\Local\Programs\Opera GX\opera.exe"

appUrl = "http://localhost:8501"
healthUrl = "http://localhost:8501/_stcore/health"

ready = False

' ============================================
' Vérifier si PokéStock tourne déjà
' ============================================

On Error Resume Next

Set http = CreateObject("MSXML2.XMLHTTP")
http.Open "GET", healthUrl, False
http.Send

If Err.Number = 0 Then
    If http.Status >= 200 And http.Status < 500 Then
        ready = True
    End If
End If

Err.Clear
On Error GoTo 0

' ============================================
' Démarrer Streamlit silencieusement si besoin
' ============================================

If Not ready Then

    shell.CurrentDirectory = projectPath

    shell.Run _
        "cmd /c python -m streamlit run app.py --server.headless true --server.port 8501", _
        0, False

    ' Attendre jusqu'à 30 secondes que PokéStock soit prêt
    For i = 1 To 60

        WScript.Sleep 500

        On Error Resume Next

        Set http = CreateObject("MSXML2.XMLHTTP")
        http.Open "GET", healthUrl, False
        http.Send

        If Err.Number = 0 Then
            If http.Status >= 200 And http.Status < 500 Then
                ready = True
                On Error GoTo 0
                Exit For
            End If
        End If

        Err.Clear
        On Error GoTo 0

    Next

End If

' ============================================
' Ouvrir PokéStock dans Opera GX
' ============================================

If ready Then

    ' Si Opera est déjà ouvert :
    ' PokéStock s'ouvre dans un nouvel onglet de la fenêtre existante.
    '
    ' Si Opera est fermé :
    ' Opera se lance directement sur PokéStock.

    shell.Run _
        Chr(34) & operaPath & Chr(34) & " " & Chr(34) & appUrl & Chr(34), _
        1, False

Else

    MsgBox _
        "PokéStock n'a pas réussi à démarrer après 30 secondes.", _
        16, _
        "PokéStock"

End If