# Fabrique les images de l'interface : fonds de boutons arrondis et icônes.
#
# Outil de développement, lancé à la main ; ses résultats sont versionnés dans
# concertcutter/ui/assets/, et l'application ne dépend que d'eux. C'est ce qui
# évite d'imposer Pillow au moment de l'exécution — le .spec l'exclut, et une
# bibliothèque d'images entière pour dessiner douze rectangles serait cher payé.
#
# Le canevas de Tk ne sait pas lisser ses tracés : un arrondi dessiné à
# l'exécution montre son escalier. GDI+, lui, antialiase — d'où le passage par
# des images, qui donnent des bords nets à n'importe quelle taille de bouton.
#
#   powershell -ExecutionPolicy Bypass -File tools/make_assets.ps1
param([string]$OutDir = "concertcutter/ui/assets")

Add-Type -AssemblyName System.Drawing

# Côté de la source. Il ne se choisit pas librement : ttk en fait la taille
# *minimale* du bouton. À 48, tous les boutons de l'écran devenaient des pavés
# de soixante pixels de haut ; à 32, ils pesaient encore trop lourd face à leur
# libellé. À 28, le minimum passe juste sous la hauteur d'une ligne de texte
# avec son rembourrage, et c'est le texte qui commande la taille du bouton.
$SIDE = 28
$RADIUS = 8
$ICON = 16

# Glissière de l'ascenseur : la largeur est figée (pas d'étirement horizontal),
# seule la hauteur s'étire. Le rayon vaut donc la demi-largeur, ce qui en fait
# une gélule.
$BAR_W = 12
$BAR_H = 28

function New-RoundedPath([single]$x, [single]$y, [single]$w, [single]$h, [single]$r) {
  $p = New-Object System.Drawing.Drawing2D.GraphicsPath
  $d = $r * 2
  $p.AddArc($x, $y, $d, $d, 180, 90)
  $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
  $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
  $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
  $p.CloseFigure()
  return $p
}

function New-Canvas([int]$w, [int]$h) {
  $bmp = New-Object System.Drawing.Bitmap $w, $h,
         ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = 'AntiAlias'
  $g.Clear([System.Drawing.Color]::Transparent)
  return @($bmp, $g)
}

function Save-Png($bmp, [string]$name) {
  $bmp.Save((Join-Path $OutDir $name), [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
}

function Write-Button([string]$name, [string]$fill, [string]$border) {
  $c = New-Canvas $SIDE $SIDE
  $bmp, $g = $c[0], $c[1]
  # Un demi-pixel de retrait : sans lui, le contour d'un pixel se dessine a
  # cheval sur le bord et ressort gris et flou au lieu de net.
  $path = New-RoundedPath 0.5 0.5 ($SIDE - 1) ($SIDE - 1) $RADIUS
  if ($fill) {
    $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml($fill))
    $g.FillPath($brush, $path); $brush.Dispose()
  }
  if ($border) {
    $pen = New-Object System.Drawing.Pen ([System.Drawing.ColorTranslator]::FromHtml($border)), 1
    $g.DrawPath($pen, $path); $pen.Dispose()
  }
  $path.Dispose(); $g.Dispose()
  Save-Png $bmp "$name.png"
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
# GDI+ ne résout pas les chemins relatifs comme PowerShell : il les rapporte au
# répertoire de travail du processus, et échoue sur une « erreur générique »
# parfaitement muette. On lui donne un chemin absolu.
$OutDir = (Resolve-Path $OutDir).Path

# Remplissage, puis bordure. Une chaîne vide veut dire « ne dessine pas ».

Write-Button 'btn_neutral_normal'   '#F7F3EA' '#C2B49F'
Write-Button 'btn_neutral_active'   '#EBE3D5' '#AB9B82'
Write-Button 'btn_neutral_pressed'  '#DFD4C0' '#9C8B72'
Write-Button 'btn_neutral_disabled' '#F2EDE2' '#DCD3C4'

Write-Button 'btn_accent_normal'    '#7A3B3B' '#7A3B3B'
Write-Button 'btn_accent_active'    '#8F4747' '#8F4747'
Write-Button 'btn_accent_pressed'   '#673131' '#673131'
Write-Button 'btn_accent_disabled'  '#F2EDE2' '#DCD3C4'

Write-Button 'btn_go_normal'        '#4E7C4A' '#4E7C4A'
Write-Button 'btn_go_active'        '#5D8F58' '#5D8F58'
Write-Button 'btn_go_pressed'       '#436B40' '#436B40'
Write-Button 'btn_go_disabled'      '#F2EDE2' '#DCD3C4'

# Fantome : rien au repos, une pastille au survol. C'est ce qui distingue une
# commande d'affichage — deplier, replier — d'une action sur le concert.
Write-Button 'btn_ghost_normal'     ''        ''
Write-Button 'btn_ghost_active'     '#EBE3D5' ''
Write-Button 'btn_ghost_pressed'    '#DFD4C0' ''
Write-Button 'btn_ghost_disabled'   ''        ''

Write-Button 'field_normal'         '#FFFFFF' '#C2B49F'
Write-Button 'field_focus'          '#FFFFFF' '#7A3B3B'
Write-Button 'field_disabled'       '#F2EDE2' '#DCD3C4'

function Write-Bar([string]$name, [string]$fill) {
  $c = New-Canvas $BAR_W $BAR_H
  $bmp, $g = $c[0], $c[1]
  # Deux pixels de retrait lateral : la gelule ne touche pas les bords du
  # couloir, sinon elle se lit comme une barre pleine et non comme un curseur.
  $path = New-RoundedPath 2 0.5 ($BAR_W - 4) ($BAR_H - 1) (($BAR_W - 4) / 2)
  $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml($fill))
  $g.FillPath($brush, $path)
  $brush.Dispose(); $path.Dispose(); $g.Dispose()
  Save-Png $bmp "$name.png"
}

Write-Bar 'scroll_normal'  '#D3C8B5'
Write-Bar 'scroll_active'  '#A8997F'

# -- icones ------------------------------------------------------------------
#
# Toutes sur la meme grille de 16, avec la meme graisse de trait : c'est la
# seule chose qui manquait aux glyphes Unicode, pioches dans des familles
# differentes et donc de poids et de tailles inegaux.

function Get-Pen([string]$ink, [single]$width = 1.6) {
  $pen = New-Object System.Drawing.Pen ([System.Drawing.ColorTranslator]::FromHtml($ink)), $width
  $pen.StartCap = 'Round'; $pen.EndCap = 'Round'; $pen.LineJoin = 'Round'
  return $pen
}

function Write-Icon([string]$name, [string]$ink, [scriptblock]$draw) {
  $c = New-Canvas $ICON $ICON
  $bmp, $g = $c[0], $c[1]
  & $draw $g $ink
  $g.Dispose()
  Save-Png $bmp "$name.png"
}

$shapes = @{
  'play'     = { param($g, $ink)
                 $b = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml($ink))
                 $pts = @((New-Object System.Drawing.PointF 4.5, 3),
                          (New-Object System.Drawing.PointF 12.5, 8),
                          (New-Object System.Drawing.PointF 4.5, 13))
                 $g.FillPolygon($b, $pts); $b.Dispose() }
  'pause'    = { param($g, $ink)
                 $b = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml($ink))
                 $g.FillRectangle($b, 4.5, 3, 2.6, 10)
                 $g.FillRectangle($b, 9.2, 3, 2.6, 10); $b.Dispose() }
  'plus'     = { param($g, $ink)
                 $p = Get-Pen $ink 1.8
                 $g.DrawLine($p, 8, 3.5, 8, 12.5); $g.DrawLine($p, 3.5, 8, 12.5, 8); $p.Dispose() }
  'minus'    = { param($g, $ink)
                 $p = Get-Pen $ink 1.8
                 $g.DrawLine($p, 3.5, 8, 12.5, 8); $p.Dispose() }
  # Deux curseurs a glissiere : lisible en 16 px, la ou une roue dentee se
  # reduit a une tache. C'est aussi ce que designe le mot « reglages ».
  'settings' = { param($g, $ink)
                 $p = Get-Pen $ink 1.5
                 $b = New-Object System.Drawing.SolidBrush ([System.Drawing.ColorTranslator]::FromHtml($ink))
                 $g.DrawLine($p, 2.5, 5, 13.5, 5)
                 $g.DrawLine($p, 2.5, 11, 13.5, 11)
                 $g.FillEllipse($b, 9, 3, 4, 4)
                 $g.FillEllipse($b, 3, 9, 4, 4)
                 $p.Dispose(); $b.Dispose() }
  'chevron_down'  = { param($g, $ink)
                      $p = Get-Pen $ink 1.6
                      $g.DrawLine($p, 4, 6.5, 8, 10.5); $g.DrawLine($p, 12, 6.5, 8, 10.5); $p.Dispose() }
  'chevron_right' = { param($g, $ink)
                      $p = Get-Pen $ink 1.6
                      $g.DrawLine($p, 6.5, 4, 10.5, 8); $g.DrawLine($p, 6.5, 12, 10.5, 8); $p.Dispose() }
}

foreach ($name in $shapes.Keys) {
  Write-Icon "ic_$name" '#3E352C' $shapes[$name]           # encre, sur fond clair
  Write-Icon "ic_${name}_light" '#FBF7F0' $shapes[$name]   # sur bouton colore
  Write-Icon "ic_${name}_muted" '#7A6E60' $shapes[$name]   # secondaire
}

Write-Output "images ecrites dans $OutDir"
