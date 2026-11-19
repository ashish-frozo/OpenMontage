# Using Huashu guidance in OpenMontage

The upstream skill is a creative and technical reference, not an installed
OpenMontage renderer. Its engine, scripts, demos and fonts are intentionally
not bundled. Do not assume that commands named in upstream `SKILL.md` exist in
this project.

For an OpenMontage request:

1. Select an existing pipeline from the user brief and inspect its stage
   instructions and approvals.
2. Use the upstream guide to choose a visual language and explain-it-through-
   motion grammar. Translate the chosen style into an OpenMontage playbook,
   `factory_style` recipe or renderer-native scene.
3. Discover an executable renderer with `factory_operations`; check its live
   health and read its declared Layer 3 skill. Do not route to Huashu's own
   runtime unless it has been installed and registered as a plugin.
4. Keep the style consistent across shots, create continuous movement within
   scenes, and preserve readable holds for narration and captions.
5. Use only rights-cleared reference images, fonts, characters and audio. The
   MIT license on Huashu source/docs does not grant rights to third-party
   material used by its demos.
