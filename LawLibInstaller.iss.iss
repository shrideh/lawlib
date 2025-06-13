[Setup]
AppName=LawLib
AppVersion=1.0.9
DefaultDirName={localappdata}\LawLib
DefaultGroupName=LawLib
OutputDir=output
OutputBaseFilename=LawLibInstaller
Compression=lzma
SolidCompression=yes
SetupIconFile=ico.ico

[Files]
Source: "dist\LawLib.exe"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\pdf_processor_gui.exe"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "nlp\*"; DestDir: "{app}\nlp"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; اختصار في قائمة ابدأ
Name: "{group}\LawLib"; Filename: "{app}\LawLib.exe"
; اختصار على سطح المكتب
Name: "{commondesktop}\LawLib"; Filename: "{app}\LawLib.exe"
; اختصار لإلغاء التثبيت في قائمة ابدأ
Name: "{group}\Uninstall LawLib"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\LawLib.exe"; Description: "تشغيل البرنامج بعد التثبيت"; Flags: nowait postinstall skipifsilent