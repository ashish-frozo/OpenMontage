import { NextResponse, type NextRequest } from 'next/server';
import { createClient } from '@/lib/supabase/server';

function safePath(value: string | null) {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return '/';
  return value;
}

export async function GET(request: NextRequest) {
  const code = request.nextUrl.searchParams.get('code');
  const next = safePath(request.nextUrl.searchParams.get('next'));
  if (!code) return NextResponse.redirect(new URL('/?notice=sign-in-expired', request.url));

  const supabase = await createClient();
  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) return NextResponse.redirect(new URL('/?notice=sign-in-expired', request.url));
  return NextResponse.redirect(new URL(next, request.url));
}
