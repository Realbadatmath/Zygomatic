#!/usr/bin/env node

// SPDX-FileCopyrightText: 2026 Zygomatic
//
// SPDX-License-Identifier: AGPL-3.0-or-later

'use strict'
// Generates hub/mc_blocks_1_20_4.json — the block manifest the Python-side
// buildability compiler reasons over.  Run offline; the output is committed so
// the hub never shells out to node at request time.
//
//   node hub/tools/dump_blocks.js
//
// Truth comes from minecraft-data 3.111.0 (the same registry mineflayer and
// mineflayer-pathfinder use at runtime), so the compiler's support model cannot
// drift from the bot's actual behaviour without this file changing too.
//
// Emitted per block:
//   bb          boundingBox ('block' | 'empty') — `block` is exactly what
//               bot.js _findRef accepts as a placement reference.
//   give        true if an item of the same name exists (`/give minecraft:<n>`
//               works AND bot.js _material can find it in the inventory).
//   full        true if the block's default state occupies the full 1x1x1 cube
//               (shape [0,0,0,1,1,1]).  Non-full blocks still support, but they
//               shift the reach face-centre, so the compiler treats them apart.
//   shapes      collision shapes of the default state, used to compute the exact
//               face centres GoalPlaceBlock measures against.
//   states      settable property names (facing/half/type/...) for oriented blocks.
//   stack       max stack size — drives the inventory-slot budget.

const fs = require('fs')
const path = require('path')

const VERSION = '1.20.4'
const mcData = require('minecraft-data')(VERSION)
const Block = require('prismarine-block')(VERSION)

const OUT = path.join(__dirname, '..', 'mc_blocks_1_20_4.json')

// prismarine-viewer ships per-block PNGs; average them for a real palette colour
// instead of hand-maintaining a colour map.
const TEX_DIR = path.join(
  __dirname, '..', '..', 'GameSim', 'minecraft', 'node_modules',
  'prismarine-viewer', 'public', 'textures', '1.20.1'
)

function textureIndex () {
  const idx = {}
  try {
    const list = JSON.parse(fs.readFileSync(path.join(TEX_DIR, 'blocks_textures.json'), 'utf8'))
    for (const e of list) {
      if (!e.texture || !e.name) continue
      if (idx[e.name]) continue // first blockState wins
      idx[e.name] = e.texture.replace(/^minecraft:blocks?\//, '')
    }
  } catch (err) {
    console.error('[dump_blocks] no texture index (' + err.message + ') — colours will be null')
  }
  return idx
}

const isFullCube = shapes =>
  shapes.length === 1 &&
  shapes[0][0] === 0 && shapes[0][1] === 0 && shapes[0][2] === 0 &&
  shapes[0][3] === 1 && shapes[0][4] === 1 && shapes[0][5] === 1

function main () {
  const texIdx = textureIndex()
  const blocks = {}
  let withTex = 0

  for (const bd of Object.values(mcData.blocksByName)) {
    let block
    try {
      block = Block.fromStateId(bd.defaultState, 0)
    } catch (_) {
      continue
    }
    const shapes = block.shapes || []
    const props = block.getProperties ? block.getProperties() : {}
    const item = mcData.itemsByName[bd.name]
    const tex = texIdx[bd.name] || null
    if (tex) withTex++

    blocks[bd.name] = {
      bb: block.boundingBox,
      give: !!item,
      full: isFullCube(shapes),
      shapes,
      states: Object.keys(props),
      stack: item ? (item.stackSize || 64) : 0,
      hardness: bd.hardness,
      tex,
      display: bd.displayName,
    }
  }

  const out = {
    _generated_by: 'hub/tools/dump_blocks.js',
    _source: 'minecraft-data ' + require('minecraft-data/package.json').version,
    version: VERSION,
    texture_dir: TEX_DIR,
    blocks,
  }
  fs.writeFileSync(OUT, JSON.stringify(out))
  const n = Object.keys(blocks).length
  const giveable = Object.values(blocks).filter(b => b.give).length
  const supports = Object.values(blocks).filter(b => b.bb === 'block').length
  console.log(`[dump_blocks] wrote ${OUT}`)
  console.log(`[dump_blocks] ${n} blocks — ${giveable} giveable, ${supports} support placement, ${withTex} with texture`)
}

main()
