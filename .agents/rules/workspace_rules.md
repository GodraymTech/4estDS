---
trigger: always_on
---

# 4estDS 工作区规则 (Workspace Rules)

- 若有artifacts，用中文。
- 当用户提到`查查`时, 你要web search。
- 如果用户的问题需要`多轮次的改代码、工具调用、命令执行`，则确保回复优先，而非行动优先。
- 如果用户的问题简单，则只需改代码，则不必保持`回复优先`，也不必做整套'实施方案 > test > walkthrough', 这能节省tokens。
- uv管理着项目虚拟环境。
- 代码编写原则: 符合第一性原理，KISS，YAGNI，高内聚、低耦合，SOLID 原则，DRY，Error能处理完善，保持项目一致性，确保性能与复杂度平衡，具备专业的设计模式