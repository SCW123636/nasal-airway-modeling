# 鼻腔 CFD 全自动链路与验收规则详解

> 版本：2026-10-16 v3（工程视角版）｜ 整理自段主对话对事实源的逐项核验（非记忆复述）
> 事实源：`plan/主计划.md`、`plan/M1第二次检查点.md`、`plan/M2出口判据重议.md`、
> `work/07_cfd_pipeline/正常路径基本方法_v1.md`、`work/07_cfd_pipeline/CFD配置与结果契约.md`、
> `outputs/M2收口/M2收口说明.md`、`outputs/T-006/数值复跑_网格vs数值.md`、
> `tasks/T-011.md`，以及 `work/lib/` 下 8 个生产脚本的源码。

**本文档口径**：只陈述**自动链路的能力与验收判据**，不涉及任何交互式操作环节，
也不作医学资格或临床可用性声明。`clinical_status: generalisation_test_only_no_human_review`
是结果契约的字段名（链路验证证据的分类标签），不是流程中的步骤。

**读法约定**：下面通篇用「你」来走这条链路——你是运行并审查这条流水线的人。
每件工具在它第一次出现的地方就地说明它是什么、为什么是它；不集中的名词表，
因为工具脱离使用场景就只是个名字。

## 0. 先给判断

如果你只有五分钟：这条链路已经做到**无人值守**——24 例副鼻窦 batch 默认 **21/24**
自动通过（opt-in 22/24），DCM → STL → 体网格 → 求解全链无交互式步骤。
你交给它一个目录，它还你一个能进求解器的鼻腔气道。

但别把"跑得通"当成"信得过"。真正的价值分歧在**判据能承担多重的结论**，
本项目把这句话做成三层可判假的边界：

1. **`auto_pass` 说的是"开口面积合理"，不是"解剖位置正确"**。前者是几何判据，后者超出本判据覆盖范围。
2. **Mesh OK 已降为记录项**，对外材料不得宣称（2026-10-14 裁定）。
3. **M3 验证矩阵至今一格未跑**；T-036~T-041 全是绕开患者矩阵的旁路，
   编号往后走 ≠ 主进程在推进。

还有一条贯穿全程的脾气，写死在代码里而非口头约定：**该停就停，不静默接受**。
五类 escalation 全部来自实测观察，无一是假设；每一类都直接上报项目负责人（Owner）裁决，
脚本自己从不为了凑通过率而放宽判据或换例。

## 1. 全链路地图

![全链路流水线与三道闸门](data:image/svg+xml;base64,PHN2ZyB2aWV3Qm94PSIwIDAgNjgwIDgxNiIgd2lkdGg9IjEwMCUiIHJvbGU9ImltZyIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHRpdGxlPm5hc2FsLWNmZCDlhajpk77ot6/mtYHmsLTnur/kuI7kuInpgZPpl7jpl6g8L3RpdGxlPgo8ZGVzYz7ku44gRElDT00g6YCJ5bqP5YiX44CB5YiG5Ymy44CB54K55L2N5o+Q5qGI44CB5bu66KGo6Z2i44CB5byA5Y+j5a6a5L2N77yM57uP6L+H5YWl5Y+j6aqM5pS25LiO6KGo6Z2i5Zub6Zeo56aB77yM6L+b5YWl5L2T572R5qC85LiOIHNpbXBsZUZvYW0g5rGC6Kej77yM5pyA5ZCO55SxIENGRCDlpZHnuqbkuI7lj4zovajlh7rlj6PliKTmja7oo4HlrprjgII8L2Rlc2M+CjxkZWZzPgo8bWFya2VyIGlkPSJhcnJvdyIgdmlld0JveD0iMCAwIDEwIDEwIiByZWZYPSI4IiByZWZZPSI1IiBtYXJrZXJXaWR0aD0iNiIgbWFya2VySGVpZ2h0PSI2IiBvcmllbnQ9ImF1dG8tc3RhcnQtcmV2ZXJzZSI+CjxwYXRoIGQ9Ik0yIDFMOCA1TDIgOSIgZmlsbD0ibm9uZSIgc3Ryb2tlPSJjb250ZXh0LXN0cm9rZSIgc3Ryb2tlLXdpZHRoPSIxLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgo8L21hcmtlcj4KPC9kZWZzPgo8cmVjdCB4PSI0MCIgeT0iNDAiIHdpZHRoPSI2MDAiIGhlaWdodD0iMjY0IiByeD0iMjAiIGZpbGw9IiNFNkYxRkIiIHN0cm9rZT0iIzE4NUZBNSIgc3Ryb2tlLXdpZHRoPSIwLjUiLz4KPHRleHQgeD0iNjAiIHk9IjYyIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiIgZm9udC1zaXplPSIxNCIgZm9udC13ZWlnaHQ9IjUwMCIgZmlsbD0iIzBDNDQ3QyI+6Zi25q615LiAIMK3IOWHoOS9lea1geawtOe6v++8iERDTSDihpIg5bim5byA5Y+j55qE5byA6KGo6Z2i77yJPC90ZXh0Pgo8cmVjdCB4PSI2MCIgeT0iNzYiIHdpZHRoPSI1NjAiIGhlaWdodD0iMzYiIHJ4PSI4IiBmaWxsPSIjRkZGRkZGIiBzdHJva2U9IiM4NUI3RUIiIHN0cm9rZS13aWR0aD0iMC41Ii8+Cjx0ZXh0IHg9Ijc2IiB5PSI5NCIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMTMiIGZpbGw9IiMwQzQ0N0MiIGRvbWluYW50LWJhc2VsaW5lPSJjZW50cmFsIj7ikaAg6YCJ5bqP5YiXIMK3IGJhdGNoMjdfc2VyaWVzX2Nob2ljZe+8iE4x77ya6L205L2N5Y6f5aeLIC8gaW4tcGxhbmUg4omkMC44bW3vvIk8L3RleHQ+CjxyZWN0IHg9IjYwIiB5PSIxMjAiIHdpZHRoPSI1NjAiIGhlaWdodD0iMzYiIHJ4PSI4IiBmaWxsPSIjRkZGRkZGIiBzdHJva2U9IiM4NUI3RUIiIHN0cm9rZS13aWR0aD0iMC41Ii8+Cjx0ZXh0IHg9Ijc2IiB5PSIxMzgiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjEzIiBmaWxsPSIjMEM0NDdDIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCI+4pGhIOWIhuWJsiDCtyBUb3RhbFNlZ21lbnRhdG9yIGhlYWRfZ2xhbmRzX2Nhdml0aWVz77yITjIvTjPvvJrkuInmoIfnrb7pnZ7nqbrvvIk8L3RleHQ+CjxyZWN0IHg9IjYwIiB5PSIxNjQiIHdpZHRoPSI1NjAiIGhlaWdodD0iMzYiIHJ4PSI4IiBmaWxsPSIjRkZGRkZGIiBzdHJva2U9IiM4NUI3RUIiIHN0cm9rZS13aWR0aD0iMC41Ii8+Cjx0ZXh0IHg9Ijc2IiB5PSIxODIiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjEzIiBmaWxsPSIjMEM0NDdDIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCI+4pGiIOeCueS9jeaPkOahiCDCtyBhdXRvX2FuYXRvbXlfbGFuZG1hcmtz77yI5Z2Q5qCH57O7ICsg5bCE57q/5oqV56WoICsg5YWx5Lqr6Z2i5ouf5ZCI77yJPC90ZXh0Pgo8cmVjdCB4PSI2MCIgeT0iMjA4IiB3aWR0aD0iNTYwIiBoZWlnaHQ9IjM2IiByeD0iOCIgZmlsbD0iI0ZGRkZGRiIgc3Ryb2tlPSIjODVCN0VCIiBzdHJva2Utd2lkdGg9IjAuNSIvPgo8dGV4dCB4PSI3NiIgeT0iMjI2IiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiIgZm9udC1zaXplPSIxMyIgZmlsbD0iIzBDNDQ3QyIgZG9taW5hbnQtYmFzZWxpbmU9ImNlbnRyYWwiPuKRoyDlu7rooajpnaIgwrcg5LiJ5qCH562+5bm26ZuGIOKIqSBIVSZsdDviiJIzMDAg4oaSIG1hcmNoaW5nIGN1YmVz77yITjTvvJpib3VuZGFyeV9lZGdlcz0w77yJPC90ZXh0Pgo8cmVjdCB4PSI2MCIgeT0iMjUyIiB3aWR0aD0iNTYwIiBoZWlnaHQ9IjM2IiByeD0iOCIgZmlsbD0iI0ZGRkZGRiIgc3Ryb2tlPSIjODVCN0VCIiBzdHJva2Utd2lkdGg9IjAuNSIvPgo8dGV4dCB4PSI3NiIgeT0iMjcwIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiIgZm9udC1zaXplPSIxMyIgZmlsbD0iIzBDNDQ3QyIgZG9taW5hbnQtYmFzZWxpbmU9ImNlbnRyYWwiPuKRpCDlvIDlj6PlrprkvY0gdjIgwrcg5oyJ55Sf5LqnIGNhcCDpnaLnp6/kuozliIbvvIhONu+8mum8u+WtlCA4MCAvIOWHuuWPoyAyNTAgbW3Csu+8iTwvdGV4dD4KPHBhdGggZD0iTTM0MCAzMDQgTDM0MCAzMzAiIGZpbGw9Im5vbmUiIHN0cm9rZT0iIzVGNUU1QSIgc3Ryb2tlLXdpZHRoPSIxLjUiIG1hcmtlci1lbmQ9InVybCgjYXJyb3cpIi8+CjxyZWN0IHg9IjQwIiB5PSIzMzYiIHdpZHRoPSIyOTAiIGhlaWdodD0iODgiIHJ4PSIxMiIgZmlsbD0iI0ZBRUVEQSIgc3Ryb2tlPSIjQkE3NTE3IiBzdHJva2Utd2lkdGg9IjAuNSIvPgo8dGV4dCB4PSI2MCIgeT0iMzYyIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiIgZm9udC1zaXplPSIxNCIgZm9udC13ZWlnaHQ9IjUwMCIgZmlsbD0iIzg1NEYwQiIgZG9taW5hbnQtYmFzZWxpbmU9ImNlbnRyYWwiPkcxIMK3IOWFpeWPo+mqjOaUtiBOMeKAk042PC90ZXh0Pgo8dGV4dCB4PSI2MCIgeT0iMzg0IiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiIgZm9udC1zaXplPSIxMiIgZmlsbD0iI0JBNzUxNyIgZG9taW5hbnQtYmFzZWxpbmU9ImNlbnRyYWwiPuS7u+S4gOS4jea7oei2syDihpIgZXNjYWxhdGVkIOi9rOS6uuW3pTwvdGV4dD4KPHRleHQgeD0iNjAiIHk9IjQwMiIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMTIiIGZpbGw9IiNCQTc1MTciIGRvbWluYW50LWJhc2VsaW5lPSJjZW50cmFsIj5iMDHigJNiMjQg6buY6K6kIDIxIOS+iyBhdXRvX3Bhc3M8L3RleHQ+CjxyZWN0IHg9IjM1MCIgeT0iMzM2IiB3aWR0aD0iMjkwIiBoZWlnaHQ9Ijg4IiByeD0iMTIiIGZpbGw9IiNGQUVFREEiIHN0cm9rZT0iI0JBNzUxNyIgc3Ryb2tlLXdpZHRoPSIwLjUiLz4KPHRleHQgeD0iMzcwIiB5PSIzNjIiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjE0IiBmb250LXdlaWdodD0iNTAwIiBmaWxsPSIjODU0RjBCIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCI+RzIgwrcg6KGo6Z2i5Zub6Zeo56aBIHN1cmZhY2VfZ2F0ZTwvdGV4dD4KPHRleHQgeD0iMzcwIiB5PSIzODQiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjEyIiBmaWxsPSIjQkE3NTE3IiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCI+d2F0ZXJ0aWdodCAvIHZvbHVtZV9jb25zZXJ2ZWQ8L3RleHQ+Cjx0ZXh0IHg9IjM3MCIgeT0iNDAyIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiIgZm9udC1zaXplPSIxMiIgZmlsbD0iI0JBNzUxNyIgZG9taW5hbnQtYmFzZWxpbmU9ImNlbnRyYWwiPm9wZW5pbmdzIOKJpTEwIG1twrIgLyBwYXRjaCDlj5jljJYg4omkMiU8L3RleHQ+CjxwYXRoIGQ9Ik0zNDAgNDI0IEwzNDAgNDUwIiBmaWxsPSJub25lIiBzdHJva2U9IiM1RjVFNUEiIHN0cm9rZS13aWR0aD0iMS41IiBtYXJrZXItZW5kPSJ1cmwoI2Fycm93KSIvPgo8cmVjdCB4PSI0MCIgeT0iNDU2IiB3aWR0aD0iNjAwIiBoZWlnaHQ9IjIyMCIgcng9IjIwIiBmaWxsPSIjRTFGNUVFIiBzdHJva2U9IiMwRjZFNTYiIHN0cm9rZS13aWR0aD0iMC41Ii8+Cjx0ZXh0IHg9IjYwIiB5PSI0NzgiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjE0IiBmb250LXdlaWdodD0iNTAwIiBmaWxsPSIjMDg1MDQxIj7pmLbmrrXkuowgwrcg5L2T572R5qC85LiO5rGC6Kej77yIV1NMIG5hdGl2ZSBGU++8jENQVSDni6zljaDovabpgZPvvIk8L3RleHQ+CjxyZWN0IHg9IjYwIiB5PSI0OTIiIHdpZHRoPSI1NjAiIGhlaWdodD0iMzYiIHJ4PSI4IiBmaWxsPSIjRkZGRkZGIiBzdHJva2U9IiM1RENBQTUiIHN0cm9rZS13aWR0aD0iMC41Ii8+Cjx0ZXh0IHg9Ijc2IiB5PSI1MTAiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjEzIiBmaWxsPSIjMDg1MDQxIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCI+4pGlIE5ldGdlbiDkvZPnvZHmoLwgwrcgbWF4aCAxLjAg4oaSIDEsMTYxLDE5NCBjZWxsc++8iHBhdGNoIOaMieW5s+mdouWHoOS9leivhuWIqyArIOmdouenr+Wvuei0pu+8iTwvdGV4dD4KPHJlY3QgeD0iNjAiIHk9IjUzNiIgd2lkdGg9IjU2MCIgaGVpZ2h0PSIzNiIgcng9IjgiIGZpbGw9IiNGRkZGRkYiIHN0cm9rZT0iIzVEQ0FBNSIgc3Ryb2tlLXdpZHRoPSIwLjUiLz4KPHRleHQgeD0iNzYiIHk9IjU1NCIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMTMiIGZpbGw9IiMwODUwNDEiIGRvbWluYW50LWJhc2VsaW5lPSJjZW50cmFsIj7ikaYgZ21zaFRvRm9hbSDihpIgcG9seU1lc2g8L3RleHQ+CjxyZWN0IHg9IjYwIiB5PSI1ODAiIHdpZHRoPSI1NjAiIGhlaWdodD0iMzYiIHJ4PSI4IiBmaWxsPSIjRkZGRkZGIiBzdHJva2U9IiM1RENBQTUiIHN0cm9rZS13aWR0aD0iMC41Ii8+Cjx0ZXh0IHg9Ijc2IiB5PSI1OTgiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjEzIiBmaWxsPSIjMDg1MDQxIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCI+4pGnIGNoZWNrTWVzaCAtYWxsR2VvbWV0cnkgLWFsbFRvcG9sb2d577yITWVzaCBPSyDlt7LpmY3kuLrorrDlvZXpobnvvIk8L3RleHQ+CjxyZWN0IHg9IjYwIiB5PSI2MjQiIHdpZHRoPSI1NjAiIGhlaWdodD0iMzYiIHJ4PSI4IiBmaWxsPSIjRkZGRkZGIiBzdHJva2U9IiM1RENBQTUiIHN0cm9rZS13aWR0aD0iMC41Ii8+Cjx0ZXh0IHg9Ijc2IiB5PSI2NDIiIGZvbnQtZmFtaWx5PSJzYW5zLXNlcmlmIiBmb250LXNpemU9IjEzIiBmaWxsPSIjMDg1MDQxIiBkb21pbmFudC1iYXNlbGluZT0iY2VudHJhbCI+4pGoIHNpbXBsZUZvYW0gwrcg6aKE6K6+IFMtQe+8iG5Ob25PcnRoQ29yciAyICsgVSAwLjcgKyBwIDAuMyArIGdyYWQgY2VsbExpbWl0ZWTvvIk8L3RleHQ+CjxwYXRoIGQ9Ik0zNDAgNjc2IEwzNDAgNzAyIiBmaWxsPSJub25lIiBzdHJva2U9IiM1RjVFNUEiIHN0cm9rZS13aWR0aD0iMS41IiBtYXJrZXItZW5kPSJ1cmwoI2Fycm93KSIvPgo8cmVjdCB4PSI0MCIgeT0iNzA4IiB3aWR0aD0iNjAwIiBoZWlnaHQ9Ijg4IiByeD0iMTIiIGZpbGw9IiNGQUVFREEiIHN0cm9rZT0iI0JBNzUxNyIgc3Ryb2tlLXdpZHRoPSIwLjUiLz4KPHRleHQgeD0iNjAiIHk9IjczNCIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMTQiIGZvbnQtd2VpZ2h0PSI1MDAiIGZpbGw9IiM4NTRGMEIiIGRvbWluYW50LWJhc2VsaW5lPSJjZW50cmFsIj5HMyDCtyBDRkQg5aWR57qmICsgTTEvTTIg5Y+M6L2o5Ye65Y+j5Yik5o2uPC90ZXh0Pgo8dGV4dCB4PSI2MCIgeT0iNzU2IiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiIgZm9udC1zaXplPSIxMiIgZmlsbD0iI0JBNzUxNyIgZG9taW5hbnQtYmFzZWxpbmU9ImNlbnRyYWwiPuS4u+WIpOaNru+8muS4jeW0qSAvIM6UcCDlhaUgMTDigJMxMDAgUGEgLyDkuI3lubPooaEg4omkMC41JSAvIOebkea1i+mHj+eos+WumjwvdGV4dD4KPHRleHQgeD0iNjAiIHk9Ijc3NCIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMTIiIGZpbGw9IiNCQTc1MTciIGRvbWluYW50LWJhc2VsaW5lPSJjZW50cmFsIj7orrDlvZXpobnvvJpyZXNpZHVhbENvbnRyb2wg5pyq6L6+IOKGkiBudW1lcmljYWxfdmFsaWRhdGlvbiA9IHVuY2hlY2tlZDwvdGV4dD4KPC9zdmc+Cg==)

先认识三个词，后面全程会用：

- **DICOM（.dcm）**：医学影像的标准格式。一卷 CT 不是一张图，而是几百张切片，
  每张都带着空间坐标和扫描参数的头信息——这是后面所有几何的源头。
- **STL**：CAD/3D 打印/CFD 圈通用的三角面片交换格式。本项目中它只是 CFD 的
  "交货单据"：鼻腔气道表面转成交互格式，交给网格生成器。**注意单位是米**，这个坑后面 §2.6 会咬人。
- **CFD（计算流体力学）**：把气道空间剖成几百万个小格子，在每个格子上解
  质量/动量守恒方程，算出哪里流速快、哪里压降大。求解器用的是 **OpenFOAM**——
  开源 CFD 工具箱，本项目固定 v1912，跑在 WSL2 Ubuntu 原生文件系统里。

一个人怎么读上面这张图：**三段工艺（几何段 / 网格段 / 求解段），夹三道性质不同的门。**
工艺负责"把东西做出来"，门负责"证明做出来的东西没坏"。
门不过，整例 escalation 停手——**不许调参绕过**，这是本项目用事故换来的规矩（§4）。

| 门 | 位置 | 性质 | 不过的后果 |
|---|---|---|---|
| G1 入口验收 N1–N6 | 几何五步出口 | 数据与几何资格 | 该例 escalated，**不许调参绕过** |
| G2 表面四门禁 | 裁剪封盖后 | 几何完整性 | 表面作废重做 |
| G3 CFD 契约 + M1/M2 双轨 | 求解后 | 数值与证据资格 | 只能声明 `unchecked`，不得宣称收敛 |

## 2. 逐步骤：要达到什么效果 → 用了什么方法

### 2.1 ① 选序列 —— 从一堆序列里挑出唯一能用于 CFD 的那条

**现场**：你打开一个患者的 CT 目录，里面躺着十几个序列——3D 重建的、剂量报告的、
定位像的、正位轴位的……你的第一个判断不是"怎么分割"，而是"哪一串切片值得信"。
选错了，后面每一步都在垃圾上绣花。

**效果**：只保留枕天真一致、面内分辨率足够的轴位原始序列，其余全部排除。

**方法**（`batch27_series_choice.py`）：
- 读取只走 `work/lib/dicom_sitk.py::load_series_sitk`。**为什么必须是 SimpleITK**
  （跨平台医学影像 IO 库，底层是 ITK/GDCM 栈）：本批数据多为
  JPEG Lossless Process 14 压缩传输语法（`1.2.840.10008.1.2.4.70`）——就是"无损压缩过的 DICOM"。
  pydicom（纯 Python 的 DICOM 读取库）缺 gdcm/pylibjpeg 插件时直接解码失败；
  SimpleITK 内置 GDCM，且 spacing/origin 由 `ImagePositionPatient`（每张切片原点的三维坐标，DICOM 头里的字段）反算，比手写可靠。
- **`SliceThickness` 不可信**（实测 3/5 例翻车）→ Δz 一律由 IPP 沿法向反算。
  教训来自现场：这个字段填错时文件照样能读，错误要到几何全错才暴露。
- `RescaleIntercept`（CT 存储值转 HU 的线性变换截距）同批出现两个值，**禁止写死**；
  滤 Secondary Capture（二次捕获图像——屏拍、重新保存的"二手"切片，不是原始扫描）；
  扩展名大小写不可靠（`.dcm` 与 `.DCM` 同批出现过）。

**判据（N1）**：`ImageType` 含 `ORIGINAL` + `AXIAL`，in-plane ≤ 0.8 mm。

### 2.2 ② 分割 —— 拿到鼻腔三块元气域

**现场**：序列选定了，现在要从几百张灰度切片里"看"出鼻腔在哪。
人靠解剖知识认，程序得靠一个已经学好的模型。

**效果**：分出左/右鼻腔 + 鼻咽的体素（voxel——三维像素，CT 的最小空间单位），
作为后续所有几何的唯一种子来源。

**方法**（`ts_nasal_seg.py`）：
- 用 **TotalSegmentator**——基于 nnU-Net 的预训练分割工具箱，开箱即认 100+ 类解剖结构，
  不用你自己训练。跑它的 `head_glands_cavities` 预训练任务（头颈部腺体与腔体类），
  只取鼻腔相关三类（省时省显存），约 **136 s/例**（CPU）。
- 权重走 hf-mirror；`--threads` 限制单例核数（多例并发会饱和镜像，与 `--jobs` 无关——这是实测结论）。
- 后处理**只取三标签**（label——分割结果里每个结构的类别编号）：
  `nasal_cavity_left` / `nasal_cavity_right` / `nasopharynx`。
- `--roi_subset` 不能与 `head_glands_cavities` 同传（只支持 total/total_mr），踩过。

**判据**：**N2** 三标签体素数 > 0；**N3** 三标签并集 ∩ HU<−300 后仍非空。
（HU——Hounsfield 单位，CT 的密度刻度：空气约 −1000，水 0，致密骨 +1000 以上。
空气取 −300 一刀，是把"肯定是气"的部分切出来。）

### 2.3 ③ 点位提案 —— 没有几何边界的开口怎么自动定位

**现场**：分割告诉你"这些体素是鼻腔"，但 CFD 需要知道**气流从哪个面进、哪个面出**。
麻烦在于：开口是气道穿出表面的一个**孔**——它没有边、没有线、没有可拟合的实体边界。
你不可能让程序"沿着孔的边缘描一遍"，因为边缘不存在。
本项目的解法是给每个开口找一个**代理平面**（位置 + 法向），后面拿这个平面去切。

**方法 A：先建跨病例可复现的解剖坐标系**（`auto_anatomy_landmarks.py:139-171`）
- 取 `hard_palate` 标签（硬腭——口腔顶部那层骨头，位置在所有病例中都稳定）∩ HU>200 的骨性体素，
  降采样至 ≤3 万点，`fit_plane`（最小二乘平面拟合——找使各点到平面距离平方和最小的平面）拟合出 `superior` 轴；
- 原点 = **左右鼻腔质心中点投影到硬腭平面**（不取扫描盒原点，换机扫描坐标不变）；
- `posterior` = 鼻咽质心 − 鼻腔质心（去掉 up 分量）；`left` = posterior × up。
- 代码注释特意写明：**硬腭平面只定坐标，不是口腔屏障**——防后人误把它当"口腔已排除"的证据。

**方法 B：鼻孔 = 前下位表面 + 向外射线投票**（`nostril_candidate`，209 行起）

思路说白了就一句：**真正的鼻孔，是你能从鼻腔内部"打一枪射出体外"的地方。**
1. 候选面 = `鼻腔标签 & CT<阈值` 的表面层（用 `binary_erosion`——形态学腐蚀，
   把掩膜整体削掉一层，削掉的就是"表面"——配 S6，即 6 邻域：上下左右前后六个方向）；
2. 只留**最前 25% + 最下 65%** 分位体素（前鼻孔体位先验）；
3. 每点打 **6 条外射线**（15/30/45/60/75/90°，步长 0.5 mm、长 12 mm），方向 = −cos(θ)·posterior − sin(θ)·up；
4. 射线"可见"的充要条件：**全程 HU<阈值**（`np.all`，**截断即弃**——不许把 FOV 外当外气；
   FOV 是扫描视野，视野之外没有数据，"没打到东西"不等于"外面是空气"）
   **且** ≥0.8 mm 内已离开语义掩膜（`semantic_departure_mm`，防把气道内部当出口）；
5. 过任一射线入选 patch → 取**最大 26-连通分量**（26-连通：体素时代"连在一起"的宽定义，
   面相邻 6 个 + 边相邻 12 个 + 角相邻 8 个都算连通；取最大块是防碎屑混入）→ 外法向 = 得票最多的方向。

**方法 C：鼻咽出口 = 两标签共享面拟合**（`interface_candidate`，182 行）
`nasopharynx` 与邻近标签**共享完整体素面**（非角接触）→ 按共面轴分组取最大面块 → 拟合平面，
`inward` = 两标签局部质心之差。产出 `secondary_patch_ratio`（第二大/最大面块比）。

**判据（N5 + 工程检查）**：`max_plane_rms_mm 1.5`（平面拟合的均方根误差）、`minimum_patch_samples 20`、
三阈值（−300/−350/−400）位姿漂移 ≤1 mm 且法向角 ≤15°（换阈值提案不能乱动——这是稳健性检查）、
`max_secondary_patch_ratio 0.35`。
源码原文注明：*Uncalibrated engineering checks, not medical accuracy or confidence probabilities.*

### 2.4 ④ 建表面 —— 从体素到水密三角面

**现场**：体素是方块，CFD 壁面要的是光滑三角面。这一步就是把"方块拼的气腔"
变成"一张闭包的皮"。

**效果**：得到可直接当 CFD 壁面的闭合表面，且不把骨壁的部分容积体素算进气道。

**方法**（`batch27_surface.py`）：
- **三标签并集，再 ∩ HU < −300**。这一刀去掉分割网络在骨壁上纳入的部分容积体素
  （一个体素里同时混了骨和空气，HU 落在中间——分割会把它划进气道，但它物理上是骨）；
  实测注释原文：不做这一刀，"a visibly thicker, rougher wall"。
- 用 **marching cubes**（1987 年的经典等值面算法：在体素场上走一遍，
  把"HU≥阈值"的边界提取成三角面片）在**体素空间**做，再套完整 LPS 仿射
  （LPS——DICOM 的标准坐标方向 Left/Posterior/Superior；仿射——把体素坐标换算到
  物理毫米坐标的缩放+平移矩阵，复用生产函数 `mask_surface`）。
- 阈值固定 −300（与试点管线一致）；−350/−400 属验证任务，**不在本步静默改**。

**判据（N4）**：`boundary_edges == 0`（边界边——只被一个三角面使用的边；
  为 0 表示这张皮完全闭合，没有裂缝）。

### 2.5 ⑤ 开口定位 v2 —— 本项目的算法核心

**现场**：三个开口有了代理平面，但平面具体搁在哪个毫米上？
往前一毫米，开口被切得太大；往后一毫米，盖住了气道。
这一段就是让程序自己找到那个位置——**全程无人，靠面积反馈闭环**。四个子步骤。

**子步骤 1：onset 检测**（`auto_opening_placement.py`）
沿平面法向从 −30 到 +30 mm、粗步长 2 mm 扫，找**截面总面积首次达 50 mm²**（`AREA_ON`）处，再二分细化到 0.25 mm。
截面算法（`cross_section_scan.py:55`）——用一个平面切一张三角网，切痕是多边形，面积用鞋带公式算：
- 取**跨平面三角形**（一端正、一端负）→ 每条边线性求交 `t = s_a/(s_a−s_b)` → **只保留恰有 2 个交点的三角**；
- 2D 投影按 1e-6 mm 精度 `np.unique` **焊接**去重（weld——把坐标重合的点合并成一个；
  不合并的话，每个跨面三角自带的那份重复交点会让图上每个点只连着一条边）
  → 邻接表（图的存法：每个点记着它与哪些点相连）→ 走闭合环 → 鞋带公式算面积。

两个实测事实支撑这个设计：marching cubes **不会**在任意平面上放顶点（1e-3 mm 内为零），
且每个跨面三角自带一份重复交点——**不焊接则每个节点度恒为 1，环永远闭不上**。

**子步骤 2：种子连通**（`connectivity_opened_surface.py:101`）
要"删掉从开口看过去的那块负侧表面"（负侧——被切平面切掉的那半边，用有符号距离判定：
  点到平面带符号的距离，负 = 在被保留的内侧）：
- 先算每顶点有符号距离，只保留**两端都负**的边建图 → `connected_components`（连通分量——
  图里互相可达的点归为同一块）。
  原因：负侧**不是一个连通块**——b01 左鼻孔碎成 349+34 个顶点，出口碎成 156+341+556+15；
  漏掉一块，cap 面积掉 9–46%。
- 种子 = **落在复核 ROI 盒内的负侧顶点**（ROI 盒——你预先圈定的一个立方体搜索区域，
  限定"只在这盒子里找起点"）；盒内无种子 → 抛 `no negative-side seed inside the reviewed ROI`。
  这就是 `seed_lost`，b05/b15/b18 三例的真实死因：ROI 盒随平面平移，其负侧储备实测只有 ~1.15 mm。
- `loop` / `hybrid` 两种备选种子已实测**会引入 50 mm 外别的开口碎片**（b01 出口），导致 cap 边界不共面被拒
  → 保留为对照臂，**不作默认**；`seed_mode=hybrid` 已列入证伪清单。

**子步骤 3：裁剪封盖**（`partitioned_surface.clip_and_cap`）
`clip_and_cap`——用平面切表面，再把切口缝上一块平面盖（cap），这样切完还是张闭合的皮。
要求源表面闭合且法向一致外指；切口边界必须是**闭合的二度环**（环上每个点恰好两条边——
  这是"能缝起来"的最低条件），否则抛
`unexpected boundary outside cutting plane or ROI`——p0 的 `clip_failed` 正是这条。

**子步骤 4：二分坐标下降**（`solve_placement`，143–266 行）
- 被控量 = **生产 `clip_and_cap` 实际产出的端盖面积**，不是截面估计。截面法有偏：
  p1 鼻孔 cap 85.95 mm² 竟大于整张截面 70.4 mm²，数学不可能。
- 起点默认 `reviewed`（2026-10-13 起）：从提案锚点平面出发，**cap 不足 80/250 目标才动**；
  每开口 9 步二分（二分查找——每次把候选区间砍半，3 mm / 2⁹ ≈ 0.006 mm），
  三开口坐标下降（多参数优化的老办法：一次只调一个开口，其余按住，轮流来），`PASSES=3`（实测第 2 轮收敛）。
- **clip 拒绝不是"开口太小"的证据，也不是无信息**：收缩上界 `hi=mid`，并把该步记入 `weak_probes`
  ——"在缺失证据上做的决策"必须与测量分开计数。
  此处踩过大坑：老版 `continue` 会死锁，并让 b02/b16/b21/b22 四个**本来通过**的例静默改变
  （出口 cap 268.51→177.44 / 259.71→50.98 / 267.48→120.25 / 250.01→219.02）。
- 汇合后 `verified_by_clip` 三态：`None`（从未进二分 = 没尝试过，**不许说"未验证"**）/
  `True` / `False`（进了二分但从没剪成功 → `placement_unverified`，一次都没量到就拒绝）。

**判据（N6）**：鼻孔 ∈ [40,140] mm²、鼻咽出口 ∈ [120,500] mm²，`decision == "auto_pass"`。

### 2.6 G2 表面四门禁

**现场**：cap 封好了，面积也进带了。但裁剪这一路刀光剑影——
切口缝对了吗？有没有偷偷多切一块？面积数字是不是虚的？
这四道门禁就是"裁剪无损"的证明。

**效果**：证明裁剪没把几何弄坏、开口真的是开口。

**方法**（`work/lib/surface_gate.py`）：
| 门禁 | 判据 |
|---|---|
| `mesh_watertight` | 边界边 / 非流形边（一条边被三个以上面共用——这在物理表面上不存在）/ 缠绕不一致 / 重复面 / 退化三角形（面积近 0 的三角）**全为 0** |
| `volume_conserved` | 裁切后 signed volume 单调不增（≤0 mm³）。signed volume——用散度定理把面积分换算成体积，符号反映面片朝向，裁剪只能变小不能变大 |
| `openings_are_open` | 每个开口 patch 有真实端盖面积（≥10 mm²） |
| `patch_areas_stable` | 每开口 patch 面积变化 ≤2% |

⚠️ **STL 单位是米 → 面积判据必须传 `unit_scale=1e6`**；传错会把 292 mm² 静默变成 2.9e-4。
native 自相交（`surfaceCheck`——OpenFOAM 自带的表面检查工具，`-checkSelfIntersection` 查三角面互相穿插）
已降级为 advisory：它在 p2/p3t1 上分别报 117/179 个点，
而那些表面闭合、流形、最小边 0.32 mm、最小质量 0.57——**判据打在必须接受的几何上，故不可用作门**。
恢复硬失败设 `NATIVE_SELF_INTERSECTION_ENFORCE=1`。

### 2.7 ⑥ 体网格 —— Netgen 与 patch 的几何识别

**现场**：STL 是张空心的皮，求解器要的是**体网格**——把这张皮围成的空间
剖成几百万个互不重叠的小四面体。这一步最阴的不是网格本身，
而是"三个开口必须被正确认成边界"：认错了，入口变墙，整场流场白算。

**效果**：把 STL 变成求解器能算的体网格，且三个开口必须被正确识别为 patch
（patch——OpenFOAM 对边界面的命名分组：哪块面是入口、哪块是出口、哪块是墙，全靠它）。

**方法**（`netgen_patient_mesh.py`）：
- **为什么不用网格生成器自带的表面描述符**：Netgen——开源自动四面体网格生成器，
  本项目实测选它。圆管对照实验里，Netgen 的 STL reader 按 `solid` 段给描述符，
  1/2/3 干净对应 inlet/outlet/wall；但在密集有机表面上，它按**相邻三角夹角**"长"出 face，
  本例返回 **11,140 个描述符**，把三个开口盖炸成无语义的碎片。**描述符编号映射不可用。**
- 改用**几何识别**：每个开口是平面盖，其平面来自导出步骤；边界三角属于某开口 **iff 其质心落在该平面上**
  （`classify`，容差 0.05 mm，一面对多面取最近）。MAPPING 固定 `{1:nostril_L, 2:nostril_R, 3:nasopharynx_outlet, 4:wall}`。
- **识别结果必须与开口阶段记录的面积对账**：b15 的 80.037 / 80.057 / 439.179 mm²。
  对不上就拒绝——本项目已经出过"输出合法但与事实不符"的门，反制手段就是**每条新判据都比对已知答案**。
- `.msh`（gmsh/Netgen 的网格文件格式）经 `netgen_vol_to_msh.convert_arrays` 写出，
  沿用其既有检查：表面必须恰好一次列出流形体积外表面、
  四面体体积与朝向必须严格为正（四面体"翻过来"会让方程系数变号）、physical-name 布局必须完整。
- `maxh=1.0` 修复版 → **1,161,194 cells**；`maxh=0.4` → 2,028,003 cells。

**判据（M1 双轨，2026-10-14 裁定）**：`checkMesh -allGeometry -allTopology`
（checkMesh——OpenFOAM 自带的网格质检工具，报非正交、畸形、开口面积等一整套指标；
注意 `cell determinant`——单元质量度量，负值/近零即畸形单元——只在带 `-allGeometry -allTopology` 时才报）。
原出口条件「Mesh OK（small determinant 数 = 0）」**未达成**（585 个 <0.001），
且两条达标路线均已证伪：降 maxh（585→494，**成本翻倍只降不消**）、双边界面修复（**81–82% 的 sliver 是修复新造的**，严重非正交面 ×6.4）。
→ 改为双轨：**主判据 = 求解不崩 + Δp 入 10–100 Pa + 质量不平衡 ≤1e-4**；
`Mesh OK` 降为记录项与精度风险提示，**对外不得宣称 Mesh OK**。

### 2.8 ⑦–⑧ 转换与诊断

**现场**：Netgen 出的是自己的 `.msh`，OpenFOAM 只认自己的 case 目录结构
（`constant/` `system/` `0/` 三件套）。这一步是翻译 + 全面体检。

`gmshToFoam`（把 gmsh 格式网格转成 OpenFOAM case 的命令行工具）→ `checkMesh -allGeometry -allTopology`。
b15 修复网格实测：585 det<0.001、114 低插值权面（插值权重——有限体积法解方程时
从面值插值到体心的权重，过低说明格子歪到算不准）、最大非正交 **87.3°**
（非正交——网格面法线与相邻单元中心连线的夹角，越大越难算准）。
**带外 direct `simpleFoam`**（不走 prescribed 封装器）：封装器对 `--allow-failed-mesh-for-diagnostic`
hard-gate 到 `tube.stl`，患者网格进不去；且 wrapper 会把 `system/` 拷进 `case/` 再跑，两者**静默分叉**
（T-006 已因此出过一次子代理误判）。规避：直接 `simpleFoam`；必须用 wrapper 时，
改配置→md5 确认→启动→启动后复核，**"是否生效"必须从运行日志行为验证，不许从文件内容推断**。

### 2.9 ⑨ 求解 —— 预设 S-A 与它治好的病

**现场**：网格就位，工况设定好，按下运行。然后才是这个项目真正交过学费的地方——
**同一张网格，有人跑崩，有人跑稳**。差别全在数值设置。这一段讲那张救了局的设置表，
以及它为什么是这张表。

**效果**：同一条网格、同一工况下稳住不崩，并给出可入 plausibility 带的 Δp。

**工况（不动）**：两鼻孔各 7.5 L/min（合计 15 L/min）固定流量、鼻咽出口 p=0（表压）、层流
（laminar——流动分层平滑、无湍流脉动的状态；鼻腔这个尺度这个流量下按层流处理）、
`nu=1.508333333333e-05`（nu——运动粘性系数，空气的"黏"的度量，单位 m²/s）、wall noSlip
（壁面无滑移——流体贴着壁面的速度必须为 0，这是黏性的直接后果）。

**S-A 数值设置（T-006 Run 1，四处修改）**。先认识四个将要登场的名词：
`nNonOrthogonalCorrectors` 是非正交修正的轮数（网格歪，就多修几轮）；
`relaxationFactors` 是松弛因子（每步只朝新解走一部分，防震荡）；
`gradSchemes` 是梯度离散格式的选择；
`residualControl` 是残差达标即停的阈值（残差——当前步与上步解的差，收敛的度量）。

| 项 | 旧值（T-004） | 新值（S-A） | 依据 |
|---|---|---|---|
| `nNonOrthogonalCorrectors` | 0 | **2** | 最大非正交 87.3°、>70° 面 204 个；惯例 2–3 |
| `relaxationFactors/equations/U` | 0.9 | **0.7** | 畸变网格惯例 |
| `relaxationFactors/fields/p` | **未设（默认 1.0 无松弛）** | **0.3** | SIMPLE 的 p 不加松弛极不稳定 |
| `gradSchemes/grad(U)` | 继承 `default Gauss linear`（无限幅） | **cellLimited Gauss linear 1** | 限幅防畸变网格上梯度振荡 |
| `residualControl` | p 1e-10 / U 1e-8 | p 1e-6 / U 1e-6 | 原值对稳态 SIMPLE 实际不可达，等于永不触发 |

（SIMPLE——压力-速度耦合的半隐式迭代算法，不可压 CFD 的主力套路：
猜压力场→解动量→修压力→再来，直到两边自洽。simpleFoam 就是它的稳态实现。）

**语法先验再跑**（"启动即验证"法）：WSL 内无 OpenFOAM 源码树，无法 grep 确认 v1912 是否支持
`fields` 子字典。先 `foamDictionary -entry endTime -set 2`（foamDictionary——命令行读写
OpenFOAM 字典文件的小工具）跑 2 步验证：日志显示每步 p 被解 **3 次**
（1 主 + 2 非正交修正），`SIMPLE: convergence criteria` 正常打印 → **`fields{p 0.3}` 写法被 v1912 接受，
且 `nNonOrthogonalCorrectors 2` 真实生效**，未静默回退。

**同网格同工况唯一变量对照（这是全项目最关键的一张表）**：

| Time | T-004 `sum local` | T-006 `sum local` |
|---|---|---|
| 100 | 0.0221 | 0.00349（小 6.3×） |
| **145** | **1.392（跳变开始）** | **0.000797（小约 1750×）** |
| 200 | 6.766 | 0.000440 |
| **260** | **sigFPE 崩溃**（浮点异常——除零之类，OpenFOAM 的直接死法） | **0.000256（越过崩溃点 273 步）** |
| 533（终局） | — | 2.26e-4（按残差平台判据终止） |

→ **「网格致命」被推翻**：同一张被 T-004 判为"致命"的网格，仅改数值设置即从崩溃变为 533 步稳定。
T-004 的发散**归因于数值设置**（`nNonOrthCorr 0` + p 无松弛 + U 0.9 的组合），
其"网格致命"判定本身是**混淆变量产物**（模板未按目标网格重新标定）。

**但新问题同时成立**：残差停在平台（Ux 9.8e-5 / p 2.6e-4，T≈460 触底后缓升 +27%），
`residualControl 1e-6` 不可达 → 新假设：**sliver 伤害"可达精度"而非"稳定性"**（H1–H4 待 M3 矩阵判别）。
这条假设已由 T-036（合成圆管 6 格）强力支持：最差合成格 p_floor 1.66e-09，
仍比患者 b15 同预设的 2.6e-4 好 5 个数量级——**无任何设置/分辨率组合能复现患者平台**。

## 3. G3：CFD 契约与 M1/M2 双轨出口

**现场**：求解器跑完了，日志躺在那儿。一个不懂契约的人会挑最高的数字去汇报；
契约的作用是规定**哪些数字有资格被说出口，说到多大声**。

### 3.1 四条主判据（M2，2026-10-14 21:00 裁定 A）

| # | 判据 | T-006 Run 1 实测 | 裕量 |
|---|---|---|---|
| 1 | 稳定不崩 | 533 步无 FOAM FATAL / sigFPE；越过 T-004 崩溃点 273 步 | — |
| 2 | Δp 入 10–100 Pa | **10.29 Pa**（面积加权 Δp_kin 8.5709 × ρ 1.2） | 贴下限 |
| 3 | 质量不平衡 ≤0.5% | 稳态段 ≤1.74e-6、终值 **7.2e-7** | ~7000× |
| 4 | 监测量稳定 | Δp 窗间相对变化 **0.0079%** | ~63× |

**记录项（对外不得宣称）**：residualControl 收敛未达 → `numerical_validation: unchecked`；
终止于 Time=533 与残差平台必须随日志摘译一并呈现（终止判据：残差停滞 200+ 步、
核心判据已全部可判、继续跑到 endTime 1500 信息增益低）。

### 3.2 契约三诊断量与取值口径（T-008 补，屏值一个不改）

| 诊断量 | 取值口径 | 屏值 |
|---|---|---|
| `mass_imbalance_fraction` | **稳态段（末段样本窗）值**；启动瞬态另列不计入（全程 max 6.33e-3 发生在 t=2，是初始场不无散的假象） | 0.005 |
| `monitor_relative_change` | Δp = 面积加权鼻孔均值静压 − 出口静压；**末 40% 样本、窗长 20**、窗口均值逐窗比取 max | 0.005 |
| `residual_max` | 终局步初始残差 | 1e-5 |

⚠️ 派生量量纲纪律：OpenFOAM 的 p 是**运动学压力**（单位 m²/s²，即压力除以密度后的形式），
**Δp(Pa) = ρ × Δp_kin，ρ = 1.2**（ρ——空气密度，约 1.2 kg/m³）。
漏乘 ρ 曾把 8.58 m²/s² 当成 8.58 Pa，误报"低于带下限"；正确值 10.29 Pa 入带。

### 3.3 结果类型：能说什么、不能说什么

| `type` | 可以展示 | 不能声称 |
|---|---|---|
| `patient_preview` | 分割表面与空间位置 | 已有患者流速、压力或湍流解 |
| `analytic_reference` | 非患者理想几何的解析场，验证显示与单位 | 患者预测或数值 CFD 求解结果 |
| `cfd_result` | 有求解器、版本、运行日志、配置与诊断记录的实际流场 | 仅凭求解完成就取得临床验证 |

`cfd_result` 的患者几何资格条件（`review.status=confirmed`、`review.method=human`、
左右鼻孔与鼻咽出口确认、口腔排除与鼻窦边界策略确认、几何 SHA-256 一致）与
`solver_adapter.status` 的完整定义见 `work/07_cfd_pipeline/CFD配置与结果契约.md`，
本文不展开。**当前契约有效患者 `cfd_result` = 0**，8 份配置 `execution_allowed=false`。

## 4. 验收规则是怎么被制定出来的

**不是设计出来的，是被事故逼出来的。** 五条立法机制，每条都能指到具体事故：

1. **先用带出处的已知答案验证**（AGENTS.md 硬约束 3）。立规原因：本项目已 **7 次**出现
   "判据输出合法但与事实不符"——自相交 det 阈值、`refine` 写成 `area>=0` 恒真、DICOM `ImageType` 索引猜错、
   **基准值跨管线混记**（p2 出口 441.87 vs 292.13，两条管线的数混成一条）、
   `ab_compare_runs.py` 把个案结论硬编码成预期从而把一次正确变更判成 FAIL、
   最新第 7 次 `diag_p0_naso_clip.py:244` 把 `mask_is_none` 写死 False。
2. **充分必要分离**。M1 原出口"Mesh OK"被 T-006 反证为**充分非必要**（同网格只改数值设置即不崩）
   → 降为记录项，并明令对外不得宣称。
3. **分层声明代替造假**。契约内置 `numerical_validation ∈ {unchecked, failed, passed_engineering_screen}`；
   没收敛就写 `unchecked`，**不许为迁就结果改屏值**。四个屏值（0.005 / 0.005 / 1e-5 / 0.05）至今逐位未动。
4. **合格率 ≠ 放行**。21/24 是 batch 指标；单个 case 该 escalated 就 escalated，
   不许为拉高合格率放宽判据或换例。`auto_opening_pipeline.py` 的五类 escalation 全部来自实测观察，无一是假设。
5. **provenance 交叉核对**。run 里同时记 `landmarks_sha256` / `surface_sha256` 并与 s5 自报读过的 sha 对账，
   **任一 MISMATCH 直接 escalated，面积照记但不作证据**。

配套协作层规则（同样是事故立的）：`VERIFIED`/`CLOSED` 只能由 Lead 打；
卡是合同，**先立约后执行**（T-041 因无卡裸跑，派跑时未识别出 50:50 分流与共同静压的口径冲突）；
T2/T3 或含数字的交付强制独立验证；报数必须抽查
（T-006 执行体 4 次不端行为：3 次虚构报数 + 被关闭后擅自重启求解覆盖 log）。

## 5. 当前状态与已知限制

**你现在站在哪儿**：几何链路健康（21/24 自动过），求解有单例达标（b15），
但契约承认的患者级结果仍是 0，且三件外部事项没有一件在我们手里。

| 验收项 | 状态 | 卡在哪 |
|---|---|---|
| K1 给定 DCM 自动出 STL | ✅ 达成（全程无交互式步骤） | — |
| K4 三例患者跑通 | ✅ 达成 | — |
| K3 STL 实际过 CFD 网格与求解 | ⚠️ b15 单例达 M1/M2 双轨 | 契约承认的 `cfd_result` 仍 = 0 |
| K5 单例耗时显著下降 | 可量化 | 阈值待需求方 |
| K2 与参照口径在解剖边界/进出口/连通性上一致 | ❌ 阻塞 | 需求方未给阈值裁定与参照口径 |

**三个真卡点（不是同一件事，别混）**：

1. **p0 例未过入口门（T-011，N6）**：`clip_failed`
   （`nasopharynx_outlet: unexpected boundary outside cutting plane or ROI`）。
   病因已独立取证：N2/s3/s4 全过（surface QC 六项全 0、boundary_edges=0）→ 非分割非几何退化；
   三开口 flood 全成功（种子 899/857/1452）→ 非 `seed_lost`（与 10-11 老病因不同，**同一 case 两种病因**）；
   失败唯一集中在 reviewed 偏移=0 处**从未被验证过**的鼻咽开口裁剪。
   对照：b01–b24 仍 **21/24 auto_pass** 与基线逐位吻合 → **v2 健康，p0 是个例**。
   路线（①就地修裁剪 ②换已 auto_pass 的底座）待 Owner 裁定。
2. **契约结果类型资格**：`cfd_result` 的患者几何资格与 `solver_adapter.status`
   的完整条件见契约文档，本文不展开；当前 `cfd_result` = 0。
3. **T-012 外部阻塞**：需求方三裁定——阈值基准（−300 vs −400）、出口口径（0 vs 18 Pa）、K2 参照口径。

## 6. 出处清单（本文每个数字的可溯源位置）

| 内容 | 出处 |
|---|---|
| 五步链路与 N1–N6 原文 | `work/07_cfd_pipeline/正常路径基本方法_v1.md` |
| M1/M2 双轨裁定全过程 | `plan/M1第二次检查点.md`、`plan/M2出口判据重议.md`、`outputs/M2收口/M2收口说明.md` |
| T-004 vs T-006 全部数值 | `outputs/T-006/数值复跑_网格vs数值.md` |
| 契约屏值与结果三类型 | `work/07_cfd_pipeline/CFD配置与结果契约.md`、`work/lib/cfd_contract.py:389-396,537` |
| 四门禁实现与单位坑 | `work/lib/surface_gate.py:32-36,44-58` |
| 开口定位算法 | `work/lib/auto_opening_pipeline.py`、`auto_opening_placement.py`、`cross_section_scan.py:55`、`connectivity_opened_surface.py:101` |
| 点位提案算法与参数 | `work/lib/auto_anatomy_landmarks.py:22-31,139-171,209-259` |
| Netgen patch 几何识别 | `work/lib/netgen_patient_mesh.py:1-33,76-90` |
| 基准值（禁手抄） | `python work/lib/print_run_table.py <run.json>` |
