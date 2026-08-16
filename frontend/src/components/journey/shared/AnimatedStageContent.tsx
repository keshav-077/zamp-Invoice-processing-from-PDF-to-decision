import { motion } from 'framer-motion'
import type { ReactNode } from 'react'

export function AnimatedStageContent({ stageKey, children }: { stageKey: string; children: ReactNode }) {
  return (
    <motion.div
      key={stageKey}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.22, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  )
}

export function StaggerSection({ children, index = 0 }: { children: ReactNode; index?: number }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, delay: index * 0.05, ease: 'easeOut' }}
    >
      {children}
    </motion.div>
  )
}
