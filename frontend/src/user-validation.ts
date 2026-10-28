import { z } from 'zod';
import { contactSchema } from './crm';

export const roles = ['ADMIN', 'SALES_MANAGER', 'SALES_REP', 'READ_ONLY'] as const;
export const userEmail = z.string().trim().min(1, '请输入有效邮箱地址。').max(254)
  .refine(value => contactSchema.shape.email.safeParse(value).success, '请输入有效邮箱地址。');
export const newPassword = z.string().min(12, '密码至少12个字符。').max(128)
  .refine(value => !!value.trim(), '密码不能全为空白。');
export const registrationSchema = z.object({ name: z.string().trim().min(1).max(100), email: userEmail,
  password: newPassword, confirm_password: z.string() }).refine(v => v.password === v.confirm_password,
  { message: '两次密码不一致。', path: ['confirm_password'] });
