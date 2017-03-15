import vapoursynth as vs
import mvmulti
import math

MSuper                 = vs.core.mvsf.Super
MAnalyze               = mvmulti.Analyze
MRecalculate           = mvmulti.Recalculate
MDegrainN              = mvmulti.DegrainN
KNLMeansCL             = vs.core.knlm.KNLMeansCL
Canny                  = vs.core.tcanny.TCanny
NNEDI                  = vs.core.nnedi3.nnedi3
RGB2OPP                = vs.core.bm3d.RGB2OPP
OPP2RGB                = vs.core.bm3d.OPP2RGB
Resample               = vs.core.fmtc.resample
Maximum                = vs.core.std.Maximum
Minimum                = vs.core.std.Minimum
Expr                   = vs.core.std.Expr
Merge                  = vs.core.std.Merge
MakeDiff               = vs.core.std.MakeDiff
MergeDiff              = vs.core.std.MergeDiff
Crop                   = vs.core.std.CropRel
AddBorders             = vs.core.std.AddBorders
Transpose              = vs.core.std.Transpose
Inflate                = vs.core.std.Inflate
MaskedMerge            = vs.core.std.MaskedMerge
ShufflePlanes          = vs.core.std.ShufflePlanes
SetFieldBased          = vs.core.std.SetFieldBased

fmtc_args              = dict(fulls=True, fulld=True)
msuper_args            = dict(hpad=0, vpad=0, sharp=2, levels=0, chroma=False)
manalyze_args          = dict(search=3, truemotion=False, trymany=True, levels=0, badrange=-24, divide=0, dct=0, chroma=False)
mrecalculate_args      = dict(truemotion=False, search=3, smooth=1, divide=0, dct=0, chroma=False)
mdegrain_args          = dict(plane=0, thscd1=16711680.0, thscd2=255.0)
canny_args             = dict(mode=1, op=0)
nnedi_args             = dict(field=1, dh=True, nns=4, qual=2, etype=1, nsize=0)

def CutOff(low, hi, p):
    def inline(src):
        upsmp          = Resample(src, src.width*2, src.height*2, kernel="gauss", a1=100, **fmtc_args)
        clip           = Resample(upsmp, src.width, src.height, kernel="gauss", a1=p, **fmtc_args)
        return clip
    hif                = MakeDiff(hi, inline(hi))
    clip               = MergeDiff(inline(low), hif)
    return clip

def Pad(src, left, right, top, bottom):
    w                  = src.width
    h                  = src.height
    clip               = Resample(src, w+left+right, h+top+bottom, -left, -top, w+left+right, h+top+bottom, kernel="point", **fmtc_args)
    return clip

def NLMeans(src, a, s, h, rclip):
    pad                = AddBorders(src, a+s, a+s, a+s, a+s)
    rclip              = AddBorders(rclip, a+s, a+s, a+s, a+s) if rclip is not None else None
    nlm                = KNLMeansCL(pad, d=0, a=a, s=s, h=h, rclip=rclip)
    clip               = Crop(nlm, a+s, a+s, a+s, a+s)
    return clip

def XYClosest(src1, src2, ref):
    clip               = Expr([src1, src2, ref], "x z - abs y z - abs > y x ?")
    return clip

class internal:
      def dilation(src, radius):
          for i in range(radius):
              src      = Maximum(src)
          return src

      def erosion(src, radius):
          for i in range(radius):
              src      = Minimum(src)
          return src

      def closing(src, radius):
          clip         = internal.dilation(src, radius)
          clip         = internal.erosion(clip, radius)
          return clip

      def opening(src, radius):
          clip         = internal.erosion(src, radius)
          clip         = internal.dilation(clip, radius)
          return clip

      def gradient(src, radius):
          erosion      = internal.erosion(src, radius)
          dilation     = internal.dilation(src, radius)
          clip         = Expr([dilation, erosion], "x y -")
          return clip

      def tophat(src, radius):
          opening      = internal.opening(src, radius)
          clip         = Expr([src, opening], "x y -")
          return clip

      def blackhat(src, radius):
          closing      = internal.closing(src, radius)
          clip         = Expr([src, closing], "y x -")
          return clip

      def super(src, pel):
          src          = Pad(src, 128, 128, 128, 128)
          clip         = Transpose(NNEDI(Transpose(NNEDI(src, **nnedi_args)), **nnedi_args))
          if pel == 4:
             clip      = Transpose(NNEDI(Transpose(NNEDI(clip, **nnedi_args)), **nnedi_args))
          return clip

      def basic(src, a, h, sharp, cutoff):
          c1           = 0.3926327792690057290863679493724
          c2           = 18.880334973195822973214959957208
          c3           = 0.5862453661304626725671053478676
          weight       = c1 * sharp * math.log(1.0 + 1.0 / (c1 * sharp))
          h_refine     = c2 * math.pow(h / c2, c3)
          upsampled    = Transpose(NNEDI(Transpose(NNEDI(src, **nnedi_args)), **nnedi_args))
          upsampled    = NLMeans(upsampled, a, 0, h, None)
          resampled    = Resample(upsampled, src.width, src.height, sx=-0.5, sy=-0.5, kernel="cubic", a1=-sharp, a2=0)
          clean        = NLMeans(src, a, 0, h, None)
          clean        = Merge(resampled, clean, weight)
          clean        = CutOff(src, clean, cutoff)
          dif          = MakeDiff(src, clean)
          dif          = NLMeans(dif, a, 1, h_refine, clean)
          clip         = MergeDiff(clean, dif)
          return clip

      def final(src, super, radius, pel, sad, sigma, alpha, beta, masking, show):
          constant     = 0.0009948813682897925944723492342
          me_sad       = constant * math.pow(sad, 2.0) * math.log(1.0 + 1.0 / (constant * sad))
          if masking:
             mask      = Canny(src[1], sigma=sigma, **canny_args)
             mask      = Expr(mask, "x {alpha} + {beta} pow {gamma} - 0.0 max 1.0 min".format(alpha=alpha, beta=beta, gamma=math.pow(alpha, beta)))
             expanded  = internal.dilation(mask, radius[1])
             closed    = internal.closing(mask, radius[1])
             mask      = Expr([expanded, closed, mask], "x y - z +")
             for i in range(radius[2]):
                 mask  = Inflate(mask)
             if show:
                return mask
          for i in range(2):
              src[i]   = Pad(src[i], 128, 128, 128, 128)
          src[1]       = MakeDiff(src[1], src[0])
          super[1]     = MakeDiff(super[1], super[0]) if super[0] is not None and super[1] is not None else None
          blankdif     = Expr(src[0], "0.0")
          supersearch  = MSuper(src[0], pelclip=super[0], rfilter=4, pel=pel, **msuper_args)
          superdif     = MSuper(src[1], pelclip=super[1], rfilter=2, pel=pel, **msuper_args)
          vmulti       = MAnalyze(supersearch, tr=radius[0], overlap=64, blksize=128, **manalyze_args)
          vmulti       = MRecalculate(supersearch, vmulti, tr=radius[0], overlap=32, blksize=64, thsad=me_sad, **mrecalculate_args)
          vmulti       = MRecalculate(supersearch, vmulti, tr=radius[0], overlap=16, blksize=32, thsad=me_sad, **mrecalculate_args)
          vmulti       = MRecalculate(supersearch, vmulti, tr=radius[0], overlap=8, blksize=16, thsad=me_sad, **mrecalculate_args)
          vmulti       = MRecalculate(supersearch, vmulti, tr=radius[0], overlap=4, blksize=8, thsad=me_sad, **mrecalculate_args)
          vmulti       = MRecalculate(supersearch, vmulti, tr=radius[0], overlap=2, blksize=4, thsad=me_sad, **mrecalculate_args)
          vmulti       = MRecalculate(supersearch, vmulti, tr=radius[0], overlap=1, blksize=2, thsad=me_sad, **mrecalculate_args)
          averaged_dif = MDegrainN(src[1], superdif, vmulti, tr=radius[0], thsad=sad, **mdegrain_args)
          averaged_dif = XYClosest(averaged_dif, src[1], blankdif)
          averaged_dif = Crop(averaged_dif, 128, 128, 128, 128)
          src[0]       = Crop(src[0], 128, 128, 128, 128)
          clean        = MergeDiff(src[0], averaged_dif)
          clip         = MaskedMerge(src[0], clean, mask) if masking else clean
          return clip

def Super(src, pel=4):
    if not isinstance(src, vs.VideoNode):
       raise TypeError("Vine.Super: src has to be a video clip!")
    elif src.format.sample_type != vs.FLOAT or src.format.bits_per_sample < 32:
       raise TypeError("Vine.Super: the sample type of src has to be single precision!")
    if not isinstance(pel, int):
       raise TypeError("Vine.Super: pel has to be an integer!")
    elif pel != 2 and pel != 4:
       raise RuntimeError("Vine.Super: pel has to be 2 or 4!")
    src                = SetFieldBased(src, 0)
    colorspace         = src.format.color_family
    if colorspace == vs.RGB:
       src             = RGB2OPP(src, 1)
    if colorspace != vs.GRAY:
       src             = ShufflePlanes(src, 0, vs.GRAY)
    clip               = internal.super(src, pel)
    return clip

def Basic(src, a=32, h=6.4, sharp=1.0, cutoff=4):
    if not isinstance(src, vs.VideoNode):
       raise TypeError("Vine.Basic: src has to be a video clip!")
    elif src.format.sample_type != vs.FLOAT or src.format.bits_per_sample < 32:
       raise TypeError("Vine.Basic: the sample type of src has to be single precision!")
    if not isinstance(a, int):
       raise TypeError("Vine.Basic: a has to be an integer!")
    elif a < 1:
       raise RuntimeError("Vine.Basic: a has to be greater than 0!")
    if not isinstance(h, float) and not isinstance(h, int):
       raise TypeError("Vine.Basic: h has to be a real number!")
    elif h <= 0:
       raise RuntimeError("Vine.Basic: h has to be greater than 0!")
    if not isinstance(sharp, float) and not isinstance(sharp, int):
       raise TypeError("Vine.Basic: sharp has to be a real number!")
    elif sharp <= 0.0:
       raise RuntimeError("Vine.Basic: sharp has to be greater than 0!")
    if not isinstance(cutoff, int):
       raise TypeError("Vine.Basic: cutoff has to be an integer!")
    elif cutoff < 1 or cutoff > 100:
       raise RuntimeError("Vine.Basic: cutoff must fall in (0, 100]!")
    src                = SetFieldBased(src, 0)
    colorspace         = src.format.color_family
    if colorspace == vs.RGB:
       src             = RGB2OPP(src, 1)
    if colorspace != vs.GRAY:
       src             = ShufflePlanes(src, 0, vs.GRAY)
    clip               = internal.basic(src, a, h, sharp, cutoff)
    return clip

def Final(src, super=[None, None], radius=[6, 1, None], pel=4, sad=400.0, sigma=0.6, alpha=0.36, beta=32.0, masking=True, show=False):
    if not isinstance(src, list):
       raise TypeError("Vine.Final: src has to be an array!")
    elif len(src) != 2:
       raise RuntimeError("Vine.Final: src has to contain 2 elements exactly!")
    elif not isinstance(src[0], vs.VideoNode) or not isinstance(src[1], vs.VideoNode):
       raise TypeError("Vine.Final: elements in src must be video clips!")
    elif src[0].format.sample_type != vs.FLOAT or src[0].format.bits_per_sample < 32:
       raise TypeError("Vine.Final: the sample type of src[0] has to be single precision!")
    elif src[1].format.id != vs.GRAYS:
       raise RuntimeError("Vine.Final: corrupted basic estimation!")
    if not isinstance(super, list):
       raise TypeError("Vine.Final: super has to be an array!")
    elif len(super) != 2:
       raise RuntimeError("Vine.Final: super has to contain 2 elements exactly!")
    for i in range(2):
        if not isinstance(super[i], vs.VideoNode) and super[i] is not None:
           raise TypeError("Vine.Final: elements in super must be video clips or None!")
        elif super[i] is not None:
           if super[i].format.id != vs.GRAYS:
              raise RuntimeError("Vine.Final: corrupted super clips!")
    if not isinstance(radius, list):
       raise TypeError("Vine.Final: radius parameter has to be an array!")
    elif len(radius) != 3:
       raise RuntimeError("Vine.Final: radius parameter has to contain 3 elements exactly!")
    for i in range(2):
        if not isinstance(radius[i], int):
           raise TypeError("Vine.Final: radius[" + str(i) + "] has to be an integer!")
    if radius[0] <= 0:
       raise RuntimeError("Vine.Final: radius[0] has to be greater than 0!")
    if radius[1] < 0:
       raise RuntimeError("Vine.Final: radius[1] has to be no less than 0!")
    if not isinstance(radius[2], int) and radius[2] is not None:
       raise TypeError("Vine.Final: radius[2] has to be an integer or None!")
    elif radius[2] is not None:
         if radius[2] < 0:
            raise RuntimeError("Vine.Final: radius[2] has to be no less than 0!")
    if not isinstance(pel, int):
       raise TypeError("Vine.Final: pel has to be an integer!")
    elif pel != 1 and pel != 2 and pel != 4:
       raise RuntimeError("Vine.Final: pel has to be 1, 2 or 4!")
    if not isinstance(sad, float) and not isinstance(sad, int):
       raise TypeError("Vine.Final: sad has to be a real number!")
    elif sad <= 0:
       raise RuntimeError("Vine.Final: sad has to be greater than 0!")
    if not isinstance(alpha, float) and not isinstance(alpha, int):
       raise TypeError("Vine.Final: alpha has to be a real number!")
    elif alpha < 0.0 or alpha > 1.0:
       raise RuntimeError("Vine.Final: alpha must fall in [0.0, 1.0]!")
    if not isinstance(beta, float) and not isinstance(beta, int):
       raise TypeError("Vine.Final: beta has to be a real number!")
    elif beta <= 1.0:
       raise RuntimeError("Vine.Final: beta has to be greater than 1.0!")
    if not isinstance(masking, bool):
       raise TypeError("Vine.Final: masking has to be boolean!")
    if not isinstance(show, bool):
       raise TypeError("Vine.Final: show has to be boolean!")
    if not masking and show:
       raise RuntimeError("Vine.Final: masking has been disabled, set masking True to show the halo mask!")
    radius[2]          = math.ceil(radius[1] / 2) if radius[2] is None else radius[2]
    for i in range(2):
        src[i]         = SetFieldBased(src[i], 0)
        super[i]       = SetFieldBased(super[i], 0) if super[i] is not None else None
    colorspace         = src[0].format.color_family
    if colorspace == vs.RGB:
       src[0]          = RGB2OPP(src[0], 1)
    if colorspace != vs.GRAY:
       src_color       = src[0]
       src[0]          = ShufflePlanes(src[0], 0, vs.GRAY)
    clip               = internal.final(src, super, radius, pel, sad, sigma, alpha, beta, masking, show)
    if colorspace != vs.GRAY:
       clip            = ShufflePlanes([clip, src_color], [0, 1, 2], vs.YUV)
    if colorspace == vs.RGB:
       clip            = OPP2RGB(clip, 1)
    return clip

def Dilation(src, radius=1):
    if not isinstance(src, vs.VideoNode):
       raise TypeError("Vine.Dilation: src has to be a video clip!")
    if not isinstance(radius, int):
       raise TypeError("Vine.Dilation: radius has to be an integer!")
    elif radius < 1:
       raise RuntimeError("Vine.Dilation: radius has to be greater than 0!")
    src                = SetFieldBased(src, 0)
    clip               = internal.dilation(src, radius)
    return clip

def Erosion(src, radius=1):
    if not isinstance(src, vs.VideoNode):
       raise TypeError("Vine.Erosion: src has to be a video clip!")
    if not isinstance(radius, int):
       raise TypeError("Vine.Erosion: radius has to be an integer!")
    elif radius < 1:
       raise RuntimeError("Vine.Erosion: radius has to be greater than 0!")
    src                = SetFieldBased(src, 0)
    clip               = internal.erosion(src, radius)
    return clip

def Closing(src, radius=1):
    if not isinstance(src, vs.VideoNode):
       raise TypeError("Vine.Closing: src has to be a video clip!")
    if not isinstance(radius, int):
       raise TypeError("Vine.Closing: radius has to be an integer!")
    elif radius < 1:
       raise RuntimeError("Vine.Closing: radius has to be greater than 0!")
    src                = SetFieldBased(src, 0)
    clip               = internal.closing(src, radius)
    return clip

def Opening(src, radius=1):
    if not isinstance(src, vs.VideoNode):
       raise TypeError("Vine.Opening: src has to be a video clip!")
    if not isinstance(radius, int):
       raise TypeError("Vine.Opening: radius has to be an integer!")
    elif radius < 1:
       raise RuntimeError("Vine.Opening: radius has to be greater than 0!")
    src                = SetFieldBased(src, 0)
    clip               = internal.opening(src, radius)
    return clip

def Gradient(src, radius=1):
    if not isinstance(src, vs.VideoNode):
       raise TypeError("Vine.Gradient: src has to be a video clip!")
    if not isinstance(radius, int):
       raise TypeError("Vine.Gradient: radius has to be an integer!")
    elif radius < 1:
       raise RuntimeError("Vine.Gradient: radius has to be greater than 0!")
    src                = SetFieldBased(src, 0)
    clip               = internal.gradient(src, radius)
    return clip

def TopHat(src, radius=1):
    if not isinstance(src, vs.VideoNode):
       raise TypeError("Vine.TopHat: src has to be a video clip!")
    if not isinstance(radius, int):
       raise TypeError("Vine.TopHat: radius has to be an integer!")
    elif radius < 1:
       raise RuntimeError("Vine.TopHat: radius has to be greater than 0!")
    src                = SetFieldBased(src, 0)
    clip               = internal.tophat(src, radius)
    return clip

def BlackHat(src, radius=1):
    if not isinstance(src, vs.VideoNode):
       raise TypeError("Vine.BlackHat: src has to be a video clip!")
    if not isinstance(radius, int):
       raise TypeError("Vine.BlackHat: radius has to be an integer!")
    elif radius < 1:
       raise RuntimeError("Vine.BlackHat: radius has to be greater than 0!")
    src                = SetFieldBased(src, 0)
    clip               = internal.blackhat(src, radius)
    return clip
