# CogTrace 齿盘核查台

在正面齿盘照片上查看齿缘像素、径向剖面和整周半径，保留检查时使用的原片。原片向右是 0°，角度在画面中顺时针增加。浅色背景、暗色齿盘适合当前按亮度找边方式。

1. 打开明确标为合成的练习，或导入单张 PNG、JPEG、TIFF、BMP 或 WebP。
2. 设置盘心、内外半径和金属亮度上限。原片点读显示亮度、距盘心半径、方向；取「选方向」可把角度填到当前核查。
3. 保存并核查，显示环带内该径线最外实测暗像素、实际源坐标，和手填齿数对应的简单角距。可查看一圈半径或当前径线。
4. 「中心通孔 · 可放圆规」把已填盘心所在像素当孔的起点，只在当前内环以内按同一亮度上限区分开口/金属，并仅保留上下左右能连回起点的开口像素，因此旁边的螺栓孔不会并入。开口碰到图边或内环边时给出复核提示。
5. 推荐圆规的规心偏离当前盘心不超过内环半径的十分之一；整像素半径保证圆周和圆内都不含实测金属，评分在可用直径与偏移之间折中，另给纯最大净空候选和最紧孔壁点。「采用推荐圆规」单独保存规心/半径，不改动原盘心与外缘读数；同一核查角度会额外给出规边到实际孔壁的余量，该方向内环内未见孔壁时余量留空（null）。PNG 校样与核查 ZIP 标出/保存规心、规圆和实际孔壁点，重开卡片仍可核对。
6. 需要交接时可下载径线 CSV、原片标注 PNG、核查 ZIP，或把原照送入准备工程。

`docker compose up --build -d --wait` 默认本机端口 19914。可使用 Python 3.11 虚拟环境安装 `requirements.txt`，然后执行 `./start.sh`。应用数据保存在独立卷或普通启动的本地数据目录。

## 圆规/通孔 HTTP 接口

- `GET /cogtrace/cards/<id>/bore?revision=n`：连通开口、泄漏/复核状态、`recommended`（折中推荐）、`largest`（纯最大直径）、`tightest` 与孔壁点。
- `POST /cogtrace/cards/<id>/compass/adopt`：空体采用推荐；也可给 `{revision,gx,gy,radius}`，偏移超内环半径 1/10、规心不在连通开口内或半径会碰到实测金属时返回 400/409。
- `POST /cogtrace/cards/<id>/compass/clear`（或 `DELETE /cogtrace/cards/<id>/compass`）：取消采用。
- `GET /cogtrace/cards/<id>/compass/ray?angle=deg`：已采用规心沿该角度的孔壁点与 `margin`，未见孔壁时 `margin` 为 `null` 并给 `reason`。
- `GET /cogtrace/cards/<id>/measurement` 在采用后带 `compass.direction.margin`、顶层 `compass_margin`/`hole_wall` 与完整 `bore`。
