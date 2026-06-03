export const DEFAULT_GENERATION_PROFILE = 'feature_first';
export const DEFAULT_FOCUS_STRENGTH = 'strong';
export const DEFAULT_FOCUS_POINTS = [
  '功能子点',
  '页面交互',
  '业务链路',
  '状态流转',
  '数据一致性',
  '异常处理'
];

export const generationProfiles = [
  {
    value: 'feature_first',
    label: '功能点优先',
    description: '拆更多入口、按钮、字段、列表、详情和状态变化。'
  },
  {
    value: 'business_flow',
    label: '业务链路优先',
    description: '强化跨页面、跨模块、数据流转和闭环校验。'
  },
  {
    value: 'exception_first',
    label: '异常边界优先',
    description: '强化失败路径、非法输入、边界值和恢复结果。'
  },
  {
    value: 'nonfunctional_first',
    label: '非功能优先',
    description: '强化性能、安全、兼容性和稳定性指标。'
  },
  {
    value: 'balanced',
    label: '均衡生成',
    description: '按功能、异常、边界和非功能做均衡覆盖。'
  }
];

export const focusStrengthOptions = [
  { value: 'strong', label: '强偏向' },
  { value: 'medium', label: '中度偏向' },
  { value: 'light', label: '轻度偏向' }
];

export const focusPointOptions = [
  '主流程',
  '功能子点',
  '页面交互',
  '业务链路',
  '状态流转',
  '权限差异',
  '边界条件',
  '异常处理',
  '数据一致性',
  '上下游联动',
  '性能',
  '安全',
  '兼容性',
  '稳定性'
];

export const buildDefaultGenerationPreferences = () => ({
  generation_profile: DEFAULT_GENERATION_PROFILE,
  focus_points: [...DEFAULT_FOCUS_POINTS],
  focus_strength: DEFAULT_FOCUS_STRENGTH
});
