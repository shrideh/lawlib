[Setup]
AppName=LawLib
AppVersion=1.0
DefaultDirName={localappdata}\LawLib
DefaultGroupName=LawLib
OutputDir=output
OutputBaseFilename=LawLibInstaller
Compression=lzma
SolidCompression=yes
SetupIconFile=icon.ico

[Files]
Source: "LawLib.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "how_to_use_it.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "indexdir\*"; DestDir: "{app}\indexdir"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "PDF_JSON\*"; DestDir: "{app}\PDF_JSON"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; اختصار في قائمة ابدأ
Name: "{group}\LawLib"; Filename: "{app}\LawLib.exe"
; اختصار على سطح المكتب
Name: "{commondesktop}\LawLib"; Filename: "{app}\LawLib.exe"
; اختصار لإلغاء التثبيت في قائمة ابدأ
Name: "{group}\Uninstall LawLib"; Filename: "{uninstallexe}"
