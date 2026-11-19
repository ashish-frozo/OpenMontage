import { createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';

const VERSION = 'aes-256-gcm-v1';
const IV_BYTES = 12;
const TAG_BYTES = 16;

function encryptionKey(): Buffer {
  const encoded = process.env.STUDIO_CREDENTIAL_ENCRYPTION_KEY;
  if (!encoded) throw new Error('Credential encryption is not configured');
  const key = Buffer.from(encoded, 'base64');
  if (key.byteLength !== 32 || key.toString('base64') !== encoded) {
    throw new Error('Credential encryption key must be canonical base64 for exactly 32 bytes');
  }
  return key;
}

export function encryptCredential(plaintext: string) {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv('aes-256-gcm', encryptionKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  return {
    ciphertext: Buffer.concat([iv, cipher.getAuthTag(), ciphertext]),
    keyVersion: VERSION,
  };
}

export function decryptCredential(payload: Uint8Array, keyVersion: string): string {
  if (keyVersion !== VERSION) throw new Error(`Unsupported credential key version: ${keyVersion}`);
  const bytes = Buffer.from(payload);
  if (bytes.byteLength <= IV_BYTES + TAG_BYTES) throw new Error('Invalid encrypted credential payload');
  const iv = bytes.subarray(0, IV_BYTES);
  const tag = bytes.subarray(IV_BYTES, IV_BYTES + TAG_BYTES);
  const ciphertext = bytes.subarray(IV_BYTES + TAG_BYTES);
  const decipher = createDecipheriv('aes-256-gcm', encryptionKey(), iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString('utf8');
}
