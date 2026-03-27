export const featureRegistry = [
  {
    id: "chat",
    routeName: "chat",
    path: "/features/chat",
    kind: "feature",
    surface: "workspace",
    name: "对话",
    kicker: "会话工作区",
    description: "只保留消息、会话历史和底部范围选择。",
    status: "主工作流",
    badge: "聊天",
    ctaLabel: "进入对话",
    enabled: true,
    highlights: ["消息流", "会话历史", "按收藏夹提问"],
  },
  {
    id: "library",
    routeName: "library",
    path: "/features/library",
    kind: "feature",
    surface: "workspace",
    name: "收藏夹",
    kicker: "内容整理",
    description: "同步收藏夹、选择视频、处理摘要与转写。",
    status: "内容页",
    badge: "收藏",
    ctaLabel: "进入收藏夹",
    enabled: true,
    highlights: ["收藏目录", "视频处理", "摘要/转写"],
  },
  {
    id: "skills-store",
    routeName: "skills-store",
    path: "/store/skills",
    kind: "store",
    surface: "marketplace",
    name: "Skills",
    kicker: "技能目录",
    description: "管理工作流技能、查看可激活能力包，并为后续 agent 行为提供可复用方法论。",
    status: "能力目录",
    badge: "技能",
    ctaLabel: "打开技能页",
    enabled: true,
    highlights: ["会话激活", "技能扫描", "方法复用"],
  },
  {
    id: "tools-store",
    routeName: "tools-store",
    path: "/store/tools",
    kind: "store",
    surface: "marketplace",
    name: "工具商店",
    kicker: "工具目录",
    description: "查看文件、命令和后续可接入执行能力，验证工具运行时与工作区隔离。",
    status: "能力目录",
    badge: "目录",
    ctaLabel: "浏览工具",
    enabled: true,
    highlights: ["工作区操作", "运行验证", "后端能力"],
  },
];

export const featureSections = [
  {
    id: "workspace",
    title: "工作区",
    description: "日常使用的主要页面",
    items: ["chat", "library"],
  },
  {
    id: "marketplace",
    title: "能力中心",
    description: "发现与扩展能力",
    items: ["skills-store", "tools-store"],
  },
];

export function findFeatureById(featureId) {
  return featureRegistry.find((item) => item.id === featureId) || null;
}

export function findFeatureByRouteName(routeName) {
  return featureRegistry.find((item) => item.routeName === routeName) || null;
}
