param([Parameter(Mandatory=$true)][string]$Msi)
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = $installer.OpenDatabase((Resolve-Path -LiteralPath $Msi).Path, 1)
# Replace only the Change Folder button's old BrowseDlg events.
$view = $database.OpenView("DELETE FROM ``ControlEvent`` WHERE ``Dialog_``='InstallDirDlg' AND ``Control_``='ChangeFolder'")
$view.Execute(); $view.Close()
foreach ($row in @(@('DoAction','PickInstallFolder','1',1),@('SetTargetPath','[WIXUI_INSTALLDIR]','1',2))) {
 $sql = 'INSERT INTO `ControlEvent` (`Dialog_`,`Control_`,`Event`,`Argument`,`Condition`,`Ordering`) VALUES (?,?,?,?,?,?)'
 $view = $database.OpenView($sql)
 $record = $installer.CreateRecord(6)
 $record.StringData(1)='InstallDirDlg';$record.StringData(2)='ChangeFolder'
 $record.StringData(3)=$row[0];$record.StringData(4)=$row[1];$record.StringData(5)=$row[2];$record.IntegerData(6)=$row[3]
 $view.Execute($record);$view.Close()
}
$database.Commit()
