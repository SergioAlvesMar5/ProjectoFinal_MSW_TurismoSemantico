param(
  [Parameter(Mandatory = $true)]
  [string]$ToolName,

  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$ToolArgs
)

function Get-ToolPath {
  param(
    [Parameter(Mandatory = $true)]
    [string]$Name
  )

  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if ($null -ne $command) {
    return $command.Source
  }

  $candidates = @()

  $localMiKTeXPath = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\MiKTeX\miktex\bin\x64'
  $candidates += (Join-Path $localMiKTeXPath ($Name + '.exe'))

  if ($env:ProgramFiles) {
    $programFilesMiKTeXPath = Join-Path $env:ProgramFiles 'MiKTeX\miktex\bin\x64'
    $candidates += (Join-Path $programFilesMiKTeXPath ($Name + '.exe'))
  }

  $programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
  if ($programFilesX86) {
    $programFilesX86MiKTeXPath = Join-Path $programFilesX86 'MiKTeX\miktex\bin\x64'
    $candidates += (Join-Path $programFilesX86MiKTeXPath ($Name + '.exe'))
  }

  foreach ($candidate in $candidates) {
    if (Test-Path $candidate) {
      return $candidate
    }
  }

  throw "No se encontró $Name. Instala MiKTeX o añade su carpeta binaria al PATH."
}

$toolPath = Get-ToolPath -Name $ToolName
& $toolPath @ToolArgs
exit $LASTEXITCODE
