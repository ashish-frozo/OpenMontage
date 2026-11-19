export type StyleCategory = 'Illustration' | 'Motion' | 'Editorial' | 'Retro';

export type StylePreset = {
  id: string;
  name: string;
  description: string;
  category: StyleCategory;
  palette: [string, string, string];
  playbook: boolean;
};

export const stylePresets: StylePreset[] = [
  { id: 'clean-professional', name: 'Clean professional', description: 'Quiet typography, confident spacing, crisp product visuals.', category: 'Editorial', palette: ['#F4F1E9', '#263B4A', '#D28B55'], playbook: true },
  { id: 'flat-motion-graphics', name: 'Flat motion graphics', description: 'Bold shapes, clear diagrams, bright transitions.', category: 'Motion', palette: ['#F7F3E9', '#223047', '#F4A44D'], playbook: true },
  { id: 'minimalist-diagram', name: 'Minimalist diagram', description: 'Sparse linework and precise visual explanations.', category: 'Motion', palette: ['#F4F3EE', '#25333B', '#6E9A8D'], playbook: true },
  { id: 'premium-minimalist', name: 'Premium minimalist', description: 'Restrained color, elegant type, deliberate pacing.', category: 'Editorial', palette: ['#181A1D', '#F5F0E6', '#C4A66C'], playbook: true },
  { id: 'anime-ghibli', name: 'Anime inspired', description: 'Hand-painted atmosphere and expressive character moments.', category: 'Illustration', palette: ['#DFE9DD', '#314D49', '#DE9B67'], playbook: true },
  { id: 'sky-spectrum', name: 'Sky spectrum', description: 'Bright science explainers with deep blue and neon accents.', category: 'Motion', palette: ['#0B1D3A', '#E2E8F0', '#8B5CF6'], playbook: true },
  { id: 'community-line-boil', name: 'Hand-drawn line boil', description: 'Tactile paper, lively hand-drawn lines, held poses.', category: 'Illustration', palette: ['#F5EBDD', '#262421', '#D85E43'], playbook: false },
  { id: 'community-isometric-25d', name: 'Isometric 2.5D', description: 'Modular objects in a measured axonometric world.', category: 'Illustration', palette: ['#F3F0E8', '#2C4057', '#4E9B88'], playbook: false },
  { id: 'community-flat-vector', name: 'Flat vector', description: 'Confident geometry, color blocks, elastic transitions.', category: 'Illustration', palette: ['#F8F2E8', '#26344A', '#EF6B4A'], playbook: false },
  { id: 'community-line-art', name: 'Continuous line art', description: 'Minimal drawings revealed one deliberate stroke at a time.', category: 'Illustration', palette: ['#F5F0E5', '#202B32', '#E58365'], playbook: false },
  { id: 'community-soft-3d', name: 'Soft 3D product', description: 'Rounded forms, tactile shadows, calm camera movement.', category: 'Illustration', palette: ['#EAE9E4', '#364354', '#88A999'], playbook: false },
  { id: 'community-shape-morph', name: 'Shape morph', description: 'A small set of forms transform to explain change.', category: 'Motion', palette: ['#F7F3EB', '#272D3B', '#E56B57'], playbook: false },
  { id: 'community-sticker-explainer', name: 'Sticker explainer', description: 'Playful layered illustrations with a cut-paper feel.', category: 'Illustration', palette: ['#F6E8D3', '#354550', '#E87B51'], playbook: false },
  { id: 'community-cyberpunk-hud', name: 'Cyberpunk HUD', description: 'A restrained sci-fi interface with luminous readouts.', category: 'Motion', palette: ['#111B28', '#D9F2E7', '#4CE0BE'], playbook: false },
  { id: 'community-collage-cutout', name: 'Collage cut-out', description: 'Paper textures, editorial layers, decisive transitions.', category: 'Editorial', palette: ['#E9DDC9', '#263B45', '#C9573E'], playbook: false },
  { id: 'community-aurora-glass', name: 'Aurora glass', description: 'Translucent panels over slow luminous color fields.', category: 'Motion', palette: ['#DDE8E6', '#26354A', '#79C7B3'], playbook: false },
  { id: 'community-geometric-bauhaus', name: 'Geometric Bauhaus', description: 'Grid-led layouts, primary geometry, rhythmic movement.', category: 'Editorial', palette: ['#F1E9D7', '#222930', '#D84F39'], playbook: false },
  { id: 'community-synthwave-vhs', name: 'Synthwave VHS', description: 'Neon horizons and subtle analog-inspired texture.', category: 'Retro', palette: ['#191633', '#FCE8E2', '#F64B91'], playbook: false },
  { id: 'community-pixel-art', name: 'Pixel art', description: 'Limited palette, crisp pixels, expressive held frames.', category: 'Retro', palette: ['#171C2C', '#F2E9C9', '#E85D75'], playbook: false },
  { id: 'community-liquid-motion', name: 'Liquid motion', description: 'Organic shapes flow, merge, and settle into new ideas.', category: 'Motion', palette: ['#F5F2EB', '#26364A', '#57B9A5'], playbook: false },
  { id: 'community-variety-captions', name: 'Bold social captions', description: 'Caption-led vertical pacing with graphic emphasis.', category: 'Editorial', palette: ['#151515', '#FFF9EA', '#F45C48'], playbook: false },
];

export const styleCategories = ['All looks', 'Illustration', 'Motion', 'Editorial', 'Retro'] as const;
export function getStylePreset(id: string) { return stylePresets.find(style => style.id === id); }
