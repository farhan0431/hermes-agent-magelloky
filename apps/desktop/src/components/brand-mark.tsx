import { cn } from '@/lib/utils'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path.replace(/^\/+/, '')}`

// Magelloku AI mark used by the zero-configuration desktop shell.
// The asset is bundled locally so packaged builds do not depend on the website.
export function BrandMark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span className={cn('inline-flex size-14 shrink-0 items-center justify-center', className)} {...props}>
      <img alt="Magelloku AI" className="size-full object-contain" src={assetPath('brand/magelloku-ai.svg')} />
    </span>
  )
}
