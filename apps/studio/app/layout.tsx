import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/500.css';
import '@fontsource/courier-prime/400.css';
import '@fontsource/courier-prime/400-italic.css';
import './globals.css';

export const metadata = {
  title: 'OpenMontage Studio',
  description: 'Research, shape, and produce your next video.',
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
