"""Web collection execution layer: unified adapters, attempt journal, and routing.

内嵌设计原则：
- anysearch 走官方 CLI 零 diff 拷贝（scripts/anysearch/），本层只做子进程透传，
  原始输出完整落盘，不重解析（无解析 bug 引入面）；
- kimi-webbridge 走 scripts/_kimi_webbridge.py 的 command() 通用透传
  （payload 与官方 curl 示例逐字段一致），本层不实现 action 协议；
- 每次采集动作必须写 13_Collection_Attempt_Journal.csv（项目内台账）；
- 登录失败/插件未连接/工具不可用必须显式记录，绝不假装采集完成。
"""
