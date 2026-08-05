$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

$assetRoot = Join-Path $PSScriptRoot "..\assets"
New-Item -ItemType Directory -Force -Path $assetRoot | Out-Null

function New-RoundedPath([float]$x, [float]$y, [float]$w, [float]$h, [float]$r) {
    $path = [System.Drawing.Drawing2D.GraphicsPath]::new()
    $d = $r * 2
    $path.AddArc($x, $y, $d, $d, 180, 90)
    $path.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $path.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $path.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    return $path
}

function New-CanvasAsset([string]$name, [int]$width, [int]$height, [scriptblock]$paint) {
    $bitmap = [System.Drawing.Bitmap]::new($width, $height, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.Clear([System.Drawing.Color]::Transparent)
    & $paint $graphics $bitmap
    $target = Join-Path $assetRoot $name
    $bitmap.Save($target, [System.Drawing.Imaging.ImageFormat]::Png)
    $graphics.Dispose()
    $bitmap.Dispose()
}

function Draw-CenteredText($g, [string]$text, [float]$size, [System.Drawing.Color]$color, [float]$x, [float]$y, [float]$w, [float]$h, [bool]$bold = $true) {
    $style = if ($bold) { [System.Drawing.FontStyle]::Bold } else { [System.Drawing.FontStyle]::Regular }
    $font = [System.Drawing.Font]::new("Segoe UI", $size, $style, [System.Drawing.GraphicsUnit]::Pixel)
    $format = [System.Drawing.StringFormat]::new()
    $format.Alignment = [System.Drawing.StringAlignment]::Center
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $brush = [System.Drawing.SolidBrush]::new($color)
    $g.DrawString($text, $font, $brush, [System.Drawing.RectangleF]::new($x, $y, $w, $h), $format)
    $brush.Dispose(); $format.Dispose(); $font.Dispose()
}

New-CanvasAsset "background.png" 1280 720 {
    param($g, $bmp)
    $sky = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
        [System.Drawing.Rectangle]::new(0, 0, 1280, 720),
        [System.Drawing.Color]::FromArgb(255, 7, 24, 58),
        [System.Drawing.Color]::FromArgb(255, 30, 116, 158),
        90
    )
    $g.FillRectangle($sky, 0, 0, 1280, 720); $sky.Dispose()

    $glow = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(42, 125, 240, 255))
    $g.FillEllipse($glow, 460, -190, 560, 430); $glow.Dispose()

    $mist = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(36, 225, 250, 255))
    foreach ($cloud in @(@(-80,78,370,66),@(330,60,460,80),@(870,92,440,70),@(90,480,420,62),@(740,470,520,72))) {
        $g.FillEllipse($mist, $cloud[0], $cloud[1], $cloud[2], $cloud[3])
    }
    $mist.Dispose()

    $star = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(130, 196, 248, 255))
    foreach ($p in @(@(98,52),@(194,91),@(312,42),@(815,56),@(956,38),@(1110,86),@(1214,44),@(706,112))) {
        $g.FillEllipse($star, $p[0], $p[1], 4, 4)
    }
    $star.Dispose()

    for ($lane = 0; $lane -lt 4; $lane++) {
        $y = 130 + ($lane * 104)
        $shadowPath = New-RoundedPath 118 ($y + 7) 1050 82 16
        $shadow = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(92, 0, 8, 26))
        $g.FillPath($shadow, $shadowPath); $shadow.Dispose(); $shadowPath.Dispose()

        $lanePath = New-RoundedPath 112 $y 1050 82 16
        $laneBrush = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
            [System.Drawing.Rectangle]::new(112, $y, 1050, 82),
            [System.Drawing.Color]::FromArgb(238, 238, 247, 255),
            [System.Drawing.Color]::FromArgb(232, 116, 174, 204),
            90
        )
        $g.FillPath($laneBrush, $lanePath); $laneBrush.Dispose()
        $edge = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(220, 146, 237, 255), 3)
        $g.DrawPath($edge, $lanePath); $edge.Dispose()
        $line = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(80, 38, 94, 130), 1)
        for ($x = 258; $x -lt 1080; $x += 112) { $g.DrawLine($line, $x, $y + 9, $x, $y + 73) }
        $line.Dispose(); $lanePath.Dispose()

        $tagPath = New-RoundedPath 22 ($y + 17) 78 48 12
        $tagBrush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(235, 4, 19, 45))
        $g.FillPath($tagBrush, $tagPath); $tagBrush.Dispose()
        $tagPen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(220, 88, 226, 255), 2)
        $g.DrawPath($tagPen, $tagPath); $tagPen.Dispose(); $tagPath.Dispose()
        Draw-CenteredText $g ("L" + ($lane + 1)) 18 ([System.Drawing.Color]::FromArgb(255,210,250,255)) 22 ($y + 17) 78 48
    }

    $hud = [System.Drawing.Drawing2D.LinearGradientBrush]::new(
        [System.Drawing.Rectangle]::new(0, 560, 1280, 160),
        [System.Drawing.Color]::FromArgb(252, 3, 12, 31),
        [System.Drawing.Color]::FromArgb(252, 9, 28, 52),
        90
    )
    $g.FillRectangle($hud, 0, 560, 1280, 160); $hud.Dispose()
    $hudLine = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(230, 93, 224, 255), 3)
    $g.DrawLine($hudLine, 0, 560, 1280, 560); $hudLine.Dispose()

    $top = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(220, 3, 14, 38))
    $g.FillRectangle($top, 0, 0, 1280, 92); $top.Dispose()
    Draw-CenteredText $g "HERO LINE // CELESTIAL BASTION" 22 ([System.Drawing.Color]::FromArgb(255,224,249,255)) 18 9 430 38
    Draw-CenteredText $g "DEPLOY • SHIFT LANES • CAST • UPGRADE" 12 ([System.Drawing.Color]::FromArgb(255,121,225,255)) 25 47 430 28 $false
}

New-CanvasAsset "lane-target.png" 860 82 {
    param($g, $bmp)
    $path = New-RoundedPath 2 2 856 78 14
    $fill = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(12, 74, 224, 255))
    $g.FillPath($fill, $path); $fill.Dispose()
    $pen = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(80, 126, 238, 255), 2)
    $pen.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash
    $g.DrawPath($pen, $path); $pen.Dispose(); $path.Dispose()
}

New-CanvasAsset "core.png" 126 142 {
    param($g, $bmp)
    $halo = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(72, 65, 231, 255))
    $g.FillEllipse($halo, 4, 5, 118, 118); $halo.Dispose()
    $ring = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 152, 247, 255), 7)
    $g.DrawEllipse($ring, 17, 18, 92, 92); $ring.Dispose()
    $crystal = [System.Drawing.PointF[]]@(
        [System.Drawing.PointF]::new(63,8),[System.Drawing.PointF]::new(94,57),
        [System.Drawing.PointF]::new(63,112),[System.Drawing.PointF]::new(32,57)
    )
    $brush = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 105, 237, 255))
    $g.FillPolygon($brush, $crystal); $brush.Dispose()
    $inner = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 233, 255, 255))
    $g.FillPolygon($inner, @([System.Drawing.PointF]::new(63,21),[System.Drawing.PointF]::new(79,58),[System.Drawing.PointF]::new(63,93),[System.Drawing.PointF]::new(49,58)))
    $inner.Dispose()
    $base = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 16, 48, 82))
    $g.FillRectangle($base, 24, 117, 78, 16); $base.Dispose()
}

New-CanvasAsset "portal.png" 108 112 {
    param($g, $bmp)
    $outer = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 203, 95, 255), 11)
    $g.DrawEllipse($outer, 10, 6, 88, 100); $outer.Dispose()
    $mid = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 103, 33, 187), 8)
    $g.DrawEllipse($mid, 23, 18, 62, 76); $mid.Dispose()
    $center = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(210, 23, 4, 54))
    $g.FillEllipse($center, 31, 26, 46, 61); $center.Dispose()
    $spark = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 245, 196, 255), 3)
    $g.DrawArc($spark, 18, 14, 70, 82, 210, 120); $g.DrawArc($spark, 25, 23, 57, 66, 20, 125); $spark.Dispose()
}

function New-HeroAsset([string]$file, [System.Drawing.Color]$accent, [string]$weapon) {
    New-CanvasAsset $file 96 96 {
        param($g, $bmp)
        $shadow = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(75,0,0,0)); $g.FillEllipse($shadow, 12, 73, 72, 17); $shadow.Dispose()
        $cape = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(240, 17, 33, 61)); $g.FillEllipse($cape, 25, 30, 47, 54); $cape.Dispose()
        $body = [System.Drawing.SolidBrush]::new($accent); $g.FillEllipse($body, 31, 27, 35, 47); $body.Dispose()
        $head = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 242, 225, 203)); $g.FillEllipse($head, 34, 9, 30, 30); $head.Dispose()
        $hair = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255, 225, 235, 250)); $g.FillPie($hair, 31, 5, 36, 38, 185, 170); $hair.Dispose()
        $outline = [System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255, 224, 251, 255), 3)
        if ($weapon -eq "shield") { $g.DrawEllipse($outline, 8, 34, 29, 38); $g.DrawLine($outline, 61, 28, 87, 65) }
        elseif ($weapon -eq "rifle") { $g.DrawLine($outline, 54, 40, 94, 25); $g.DrawLine($outline, 64, 47, 94, 35) }
        elseif ($weapon -eq "shotgun") { $g.DrawLine($outline, 53, 41, 92, 49); $g.DrawLine($outline, 58, 47, 91, 56) }
        else { $g.DrawRectangle($outline, 53, 30, 39, 18); $g.DrawLine($outline, 60, 49, 54, 68) }
        $outline.Dispose()
        $badge = [System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(235, 3, 15, 35)); $g.FillEllipse($badge, 4, 4, 24, 24); $badge.Dispose()
        $badgePen = [System.Drawing.Pen]::new($accent, 2); $g.DrawEllipse($badgePen, 4, 4, 24, 24); $badgePen.Dispose()
    }
}

$heroDefs = @(
    @{File="hero-aegis.png"; Color=[System.Drawing.Color]::FromArgb(255,69,197,255); Weapon="shield"; Name="AEGIS"; Role="BLOCK"},
    @{File="hero-rifle.png"; Color=[System.Drawing.Color]::FromArgb(255,255,118,164); Weapon="rifle"; Name="RIFLE"; Role="FOCUS"},
    @{File="hero-shotgun.png"; Color=[System.Drawing.Color]::FromArgb(255,255,186,82); Weapon="shotgun"; Name="SHOTGUN"; Role="PUSH"},
    @{File="hero-rocket.png"; Color=[System.Drawing.Color]::FromArgb(255,179,104,255); Weapon="rocket"; Name="ROCKET"; Role="BLAST"}
)

foreach ($hero in $heroDefs) { New-HeroAsset $hero.File $hero.Color $hero.Weapon }

for ($i = 0; $i -lt $heroDefs.Count; $i++) {
    $hero = $heroDefs[$i]
    $heroFile = Join-Path $assetRoot $hero.File
    New-CanvasAsset ("card-" + ($i + 1) + ".png") 170 106 {
        param($g, $bmp)
        $path = New-RoundedPath 2 2 166 102 12
        $fill = [System.Drawing.Drawing2D.LinearGradientBrush]::new([System.Drawing.Rectangle]::new(2,2,166,102),[System.Drawing.Color]::FromArgb(245,7,22,46),[System.Drawing.Color]::FromArgb(245,20,55,78),90)
        $g.FillPath($fill,$path); $fill.Dispose()
        $pen=[System.Drawing.Pen]::new($hero.Color,3); $g.DrawPath($pen,$path); $pen.Dispose(); $path.Dispose()
        $portrait=[System.Drawing.Image]::FromFile($heroFile); $g.DrawImage($portrait,4,9,80,80); $portrait.Dispose()
        Draw-CenteredText $g $hero.Name 15 ([System.Drawing.Color]::White) 78 15 88 30
        Draw-CenteredText $g $hero.Role 11 $hero.Color 80 43 84 22
        Draw-CenteredText $g ("DEPLOY " + @(30,35,40,50)[$i]) 10 ([System.Drawing.Color]::FromArgb(255,189,229,242)) 75 72 92 20 $false
    }

    New-CanvasAsset ("skill-" + ($i + 1) + ".png") 92 40 {
        param($g, $bmp)
        $path=New-RoundedPath 1 1 90 38 9
        $fill=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(235,$hero.Color.R,$hero.Color.G,$hero.Color.B)); $g.FillPath($fill,$path); $fill.Dispose()
        $pen=[System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255,245,253,255),2); $g.DrawPath($pen,$path); $pen.Dispose(); $path.Dispose()
        Draw-CenteredText $g ("SKILL " + (20 + (($i + 1) * 5))) 11 ([System.Drawing.Color]::FromArgb(255,5,19,38)) 0 0 92 40
    }

    New-CanvasAsset ("upgrade-" + ($i + 1) + ".png") 92 34 {
        param($g, $bmp)
        $path=New-RoundedPath 1 1 90 32 8
        $fill=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(230,18,43,66)); $g.FillPath($fill,$path); $fill.Dispose()
        $pen=[System.Drawing.Pen]::new($hero.Color,2); $g.DrawPath($pen,$path); $pen.Dispose(); $path.Dispose()
        Draw-CenteredText $g ("UP +" + (10 + (($i + 1) * 10))) 10 ([System.Drawing.Color]::White) 0 0 92 34
    }
}

New-CanvasAsset "selection.png" 170 106 {
    param($g, $bmp)
    $path=New-RoundedPath 3 3 164 100 12
    $glow=[System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255,255,225,105),5); $g.DrawPath($glow,$path); $glow.Dispose(); $path.Dispose()
}

function New-EnemyAsset([string]$file, [System.Drawing.Color]$accent, [string]$kind, [int]$spikes) {
    New-CanvasAsset $file 84 74 {
        param($g,$bmp)
        $shadow=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(75,0,0,0)); $g.FillEllipse($shadow,10,57,64,12); $shadow.Dispose()
        $body=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255,24,18,45)); $g.FillEllipse($body,14,18,56,44); $body.Dispose()
        $armor=[System.Drawing.SolidBrush]::new($accent); $g.FillEllipse($armor,20,24,44,31); $armor.Dispose()
        $dark=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255,53,27,80));
        for($s=0;$s -lt $spikes;$s++){
            $sx=18+($s*([math]::Max(1,48/[math]::Max(1,$spikes-1))))
            $g.FillPolygon($dark,@([System.Drawing.PointF]::new($sx,27),[System.Drawing.PointF]::new($sx+4,5),[System.Drawing.PointF]::new($sx+10,28)))
        }
        $dark.Dispose()
        $eye=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255,246,226,255)); $g.FillEllipse($eye,29,32,8,8); $g.FillEllipse($eye,50,32,8,8); $eye.Dispose()
        $pupil=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(255,255,50,166)); $g.FillEllipse($pupil,31,34,4,4); $g.FillEllipse($pupil,52,34,4,4); $pupil.Dispose()
        if($kind -eq 'flyer') { $wing=[System.Drawing.Pen]::new($accent,5); $g.DrawArc($wing,-4,21,34,30,190,130); $g.DrawArc($wing,56,21,34,30,220,130); $wing.Dispose() }
        if($kind -eq 'boss') { $crown=[System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255,255,210,92),5); $g.DrawLine($crown,20,17,28,3); $g.DrawLine($crown,28,3,42,15); $g.DrawLine($crown,42,15,57,2); $g.DrawLine($crown,57,2,67,18); $crown.Dispose() }
    }
}

New-EnemyAsset "enemy-scout.png" ([System.Drawing.Color]::FromArgb(255,202,83,255)) "ground" 2
New-EnemyAsset "enemy-grunt.png" ([System.Drawing.Color]::FromArgb(255,255,83,153)) "ground" 3
New-EnemyAsset "enemy-armored.png" ([System.Drawing.Color]::FromArgb(255,114,121,168)) "ground" 4
New-EnemyAsset "enemy-flyer.png" ([System.Drawing.Color]::FromArgb(255,72,220,255)) "flyer" 2
New-EnemyAsset "enemy-elite.png" ([System.Drawing.Color]::FromArgb(255,255,130,56)) "ground" 5
New-EnemyAsset "enemy-boss.png" ([System.Drawing.Color]::FromArgb(255,151,42,220)) "boss" 6

$projectileColors=@(
    [System.Drawing.Color]::FromArgb(255,106,229,255),
    [System.Drawing.Color]::FromArgb(255,255,128,177),
    [System.Drawing.Color]::FromArgb(255,255,199,91),
    [System.Drawing.Color]::FromArgb(255,197,119,255)
)
for($i=0;$i -lt 4;$i++){
    $pc=$projectileColors[$i]
    New-CanvasAsset ("projectile-"+($i+1)+".png") 34 18 {
        param($g,$bmp)
        $glow=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb(90,$pc.R,$pc.G,$pc.B)); $g.FillEllipse($glow,0,1,34,16); $glow.Dispose()
        $beam=[System.Drawing.SolidBrush]::new($pc); $g.FillEllipse($beam,7,5,25,8); $beam.Dispose()
        $white=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::White); $g.FillEllipse($white,20,7,10,4); $white.Dispose()
    }
}

for($frame=1;$frame -le 4;$frame++){
    $radius=8+($frame*7)
    $alpha=255-(($frame-1)*55)
    New-CanvasAsset ("impact-"+$frame+".png") 72 72 {
        param($g,$bmp)
        $outer=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb($alpha,255,83,184)); $g.FillEllipse($outer,36-$radius,36-$radius,$radius*2,$radius*2); $outer.Dispose()
        $inner=[System.Drawing.SolidBrush]::new([System.Drawing.Color]::FromArgb($alpha,255,235,142)); $g.FillEllipse($inner,36-($radius/2),36-($radius/2),$radius,$radius); $inner.Dispose()
    }
}

New-CanvasAsset "end-panel.png" 700 250 {
    param($g,$bmp)
    $path=New-RoundedPath 4 4 692 242 24
    $fill=[System.Drawing.Drawing2D.LinearGradientBrush]::new([System.Drawing.Rectangle]::new(4,4,692,242),[System.Drawing.Color]::FromArgb(248,4,13,35),[System.Drawing.Color]::FromArgb(248,40,16,62),90)
    $g.FillPath($fill,$path); $fill.Dispose()
    $pen=[System.Drawing.Pen]::new([System.Drawing.Color]::FromArgb(255,129,231,255),4); $g.DrawPath($pen,$path); $pen.Dispose(); $path.Dispose()
    Draw-CenteredText $g "CELESTIAL BASTION" 18 ([System.Drawing.Color]::FromArgb(255,149,236,255)) 0 18 700 35
    Draw-CenteredText $g "PRESS ENTER / TAP TO RESTART" 16 ([System.Drawing.Color]::FromArgb(255,235,244,255)) 0 188 700 35 $false
}

function Write-Tone([string]$file,[double]$frequency,[double]$duration,[double]$volume,[string]$shape="sine") {
    $sampleRate=22050
    $count=[int]($sampleRate*$duration)
    $bytes=[byte[]]::new($count*2)
    for($i=0;$i -lt $count;$i++){
        $t=$i/$sampleRate
        $env=[math]::Pow([math]::Max(0,1-($i/$count)),1.5)
        $phase=2*[math]::PI*$frequency*$t
        $wave=if($shape -eq "square"){if([math]::Sin($phase)-ge 0){1}else{-1}}elseif($shape -eq "noise"){(Get-Random -Minimum -1000 -Maximum 1001)/1000}else{[math]::Sin($phase)}
        $value=[int16]([math]::Max(-32767,[math]::Min(32767,$wave*$env*$volume*32767)))
        $pair=[BitConverter]::GetBytes($value); $bytes[$i*2]=$pair[0]; $bytes[$i*2+1]=$pair[1]
    }
    $stream=[IO.File]::Create((Join-Path $assetRoot $file)); $writer=[IO.BinaryWriter]::new($stream)
    $writer.Write([Text.Encoding]::ASCII.GetBytes("RIFF")); $writer.Write(36+$bytes.Length); $writer.Write([Text.Encoding]::ASCII.GetBytes("WAVE"))
    $writer.Write([Text.Encoding]::ASCII.GetBytes("fmt ")); $writer.Write(16); $writer.Write([int16]1); $writer.Write([int16]1); $writer.Write($sampleRate); $writer.Write($sampleRate*2); $writer.Write([int16]2); $writer.Write([int16]16)
    $writer.Write([Text.Encoding]::ASCII.GetBytes("data")); $writer.Write($bytes.Length); $writer.Write($bytes); $writer.Dispose(); $stream.Dispose()
}

Write-Tone "sfx-deploy.wav" 520 0.18 0.32 "sine"
Write-Tone "sfx-shot.wav" 760 0.10 0.18 "square"
Write-Tone "sfx-hit.wav" 170 0.16 0.28 "noise"
Write-Tone "sfx-skill.wav" 360 0.42 0.30 "sine"
Write-Tone "sfx-core.wav" 95 0.40 0.38 "square"
Write-Tone "sfx-victory.wav" 660 0.70 0.28 "sine"
Write-Tone "sfx-defeat.wav" 82 0.85 0.32 "sine"

Write-Output "Generated PNG and WAV assets in $assetRoot"
