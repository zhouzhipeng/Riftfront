// This script plays the game and checks it behaves as expected.
// It runs inside the game: use `harness` to play frames, simulate
// the player inputs and inspect the objects of the scene.

// The game starts on its first scene. You can jump to any scene:
await harness.goToScene('Teste');

// Play one second of the game (60 frames):
await harness.stepFrames(60);

// Simulate the player pressing a key (also see setMousePosition,
// setMouseButtonPressed, touchStart...):
// harness.setKeyPressed('Right', true);
// await harness.stepFrames(30);
// harness.setKeyPressed('Right', false);

// Inspect objects and check the game state - a failed assert fails the test:
// const players = harness.getObjects('Player');
// harness.assert(players.length === 1, 'The player is in the scene');

console.log('Scene at the end of the test:', harness.getSceneName());
