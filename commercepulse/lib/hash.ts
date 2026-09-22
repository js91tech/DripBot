export function hashString(input: string) {
  let hash = 2166136261;
  for (let i = 0; i < input.length; i += 1) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function seededUnit(hash: number, salt = 0) {
  const x = Math.sin(hash + salt * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

export function seededInt(hash: number, min: number, max: number, salt = 0) {
  return Math.round(min + seededUnit(hash, salt) * (max - min));
}

export function clamp(value: number, min = 0, max = 100) {
  return Math.min(max, Math.max(min, Math.round(value)));
}
