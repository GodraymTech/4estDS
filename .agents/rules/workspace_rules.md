---
trigger: always_on
---

# 工作区规则 (Workspace Rules)

- DO NOT send optional commentary.
- 代码编写原则: 
  - 符合第一性原理、KISS、YAGNI、高内聚低耦合原则、SOLID 原则、DRY；
  - Error能处理完善
  - 保持项目一致性
  - 确保性能与复杂度平衡
  - 具备专业的设计模式，符合业内最佳实践
  - 要有框架思维: 当用户有增删改/重构代码的需求, 要先思考它对项目架构的影响, 再带着整体框架来解决问题
- 与用户交互的原则:
  - 所有回复内容的非代码部分, 必须中文优先 (包括各种artifacts)
  - 永远是回复优先，而非行动优先;
  - 禁止擅自操作浏览器: 如果你想亲自操作浏览器，必须先主动征求我同意;
  - 简化交互, 节省token: 
    - 任务简单时: 不准编排`实施方案, task list, walkthrough, test`;
    - 当出于debug的需要时: 你可以直自己创建/删除辅助代码文件, 而无需征得我的同意!
  - 善用web search
- 命令执行原则:
  - 项目中, Python虚拟环境用uv; 前端环境用mise和pnpm
  - 当某个命令需要沙箱外的资源, 且你没有沙箱外的权限时, 别着急降级执行, 先主动问我是否同意
  - 禁止污染环境: 你因为调试生成的中间文件产物，务必自行删除
- 其他事项:
  - 需要模型时，去`.4estDS/models`找
  - 需要供测试的图像时，去`data/for_test`找
  - 编码不要有历史包袱，我将删掉旧数据库文件，你不必做兼容
  - **生产侧发布 SOP (同步生产侧)**:
    - 生产模式：单端口 8000 SPA，无 `.git` 依赖，制品发布至 `~/rays/release/4estds`，由 `systemd --user` 服务 `4estds` 托管
    - 标准发布流程（极速，不要二次冗余构建或搜寻）：
      1. `git commit -m "..."`
      2. `git tag -a <version> -m "..."`
      3. `./scripts/release.sh <version>` (脚本自带 Vite build、无 dev 依赖打包、原子切换当前软链)
      4. `systemctl --user restart 4estds` (重启生效)