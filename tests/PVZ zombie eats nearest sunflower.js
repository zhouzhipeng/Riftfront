await harness.goToScene('PVZ Battle', { skipCreatingInstances: true });

const fartherSunflower = harness.spawn('SunflowerPlant', 400, 300, 5);
const nearerSunflower = harness.spawn('SunflowerPlant', 700, 300, 5);
const zombie = harness.spawn('Zombie', 780, 300, 5);

const enteredAttack = await harness.stepUntil(
  () => harness.getObjectVariable(zombie.id, 'Attacking')?.value === 1,
  { maxFrames: 150 }
);
harness.assert(
  enteredAttack,
  'The zombie must enter its attack state within 150 simulated frames.'
);

const zombieAtContact = harness
  .getObjects('Zombie')
  .find(instance => instance.id === zombie.id);
harness.assert(
  !!zombieAtContact && zombieAtContact.x < 750,
  `The zombie must cross the former 80-pixel stop point before attacking; x was ${
    zombieAtContact ? zombieAtContact.x : 'missing'
  }.`
);

const ateNearerSunflower = await harness.stepUntil(
  () =>
    !harness
      .getObjects('SunflowerPlant')
      .some(instance => instance.id === nearerSunflower.id),
  { maxFrames: 220 }
);
harness.assert(
  ateNearerSunflower,
  'Three collision-gated bites must consume the nearer sunflower.'
);

await harness.stepFrames(1);

const remainingSunflowers = harness.getObjects('SunflowerPlant');
harness.assert(
  remainingSunflowers.length === 1 &&
    remainingSunflowers[0].id === fartherSunflower.id,
  `The farther sunflower must survive; remaining ids were ${remainingSunflowers
    .map(instance => instance.id)
    .join(', ') || 'none'}.`
);

const retargetedX = harness.getObjectVariable(zombie.id, 'TargetX')?.value;
harness.assert(
  retargetedX === 400,
  `After eating the nearer sunflower, the zombie must target the survivor at x=400; TargetX was ${retargetedX}.`
);

const playedEatSound = harness
  .getPlayedSounds()
  .some(entry => entry.sound === 'PVZ_ZombieEat');
harness.assert(
  playedEatSound,
  'The completed bite sequence must play the zombie eating sound.'
);

harness.watch('Zombie');
harness.watch('SunflowerPlant');
