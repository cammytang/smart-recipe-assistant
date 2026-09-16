import { test } from 'node:test'
import assert from 'node:assert/strict'
import { groupShopping, parseRecipe } from './recipeView.js'

test('parses Markdown tables, numbered steps, continuation text and metadata', () => {
  const recipe = parseRecipe('## 菜品详细整理结果\n### 食材清单\n| 食材 | 用量 |\n| --- | --- |\n| 土豆 | 2个 |\n### 烹饪步骤\n1. 去皮切丝\n用清水冲洗。\n2. 热锅炒熟\n### 总耗时\n15分钟\n### 烹饪小贴士\n少油。')
  assert.deepEqual(recipe.ingredients, ['土豆 2个'])
  assert.deepEqual(recipe.steps, ['去皮切丝\n用清水冲洗。', '热锅炒熟'])
  assert.equal(recipe.duration, '15分钟')
  assert.deepEqual(recipe.notes, ['少油。'])
})

test('merges shared ingredients, converts compatible units and retains incompatible units', () => {
  const groups = groupShopping(['土豆 2个（用于：土豆丝、土豆泥）', '土豆 1个（用于：炖菜）', '土豆 100克', '鸡胸肉 0.5千克', '鸡胸肉 200克', '盐 适量', '盐 少许'])
  assert.equal(groups['蔬菜区'][0].quantity, '5个 + 100克')
  assert.equal(groups['肉禽区'][0].quantity, '700克')
  assert.equal(groups['调料区'][0].quantity, '适量 + 少许')
})

test('preserves unrecognized quantities without inventing totals', () => {
  const groups = groupShopping(['土豆 1-2个', '盐适量'])
  assert.equal(groups['蔬菜区'][0].name, '土豆 1-2个')
  assert.equal(parseRecipe('暂无可用信息').steps.length, 0)
})
