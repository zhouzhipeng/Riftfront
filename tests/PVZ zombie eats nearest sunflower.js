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

await harness.goToScene('PVZ Battle', { skipCreatingInstances: true });

const finalSunflower = harness.spawn('SunflowerPlant', 700, 300, 5);
const finalZombie = harness.spawn('Zombie', 735, 300, 5);
harness.setObjectVariable(finalSunflower.id, 'HP', 1);

const attackedFinalSunflower = await harness.stepUntil(
  () => harness.getObjectVariable(finalZombie.id, 'Attacking')?.value === 1,
  { maxFrames: 15 }
);
harness.assert(
  attackedFinalSunflower,
  'The zombie must enter its attack state against the final sunflower.'
);

const consumedFinalSunflower = await harness.stepUntil(
  () => harness.getObjects('SunflowerPlant').length === 0,
  { maxFrames: 90 }
);
harness.assert(
  consumedFinalSunflower,
  'The zombie must consume the final sunflower through its normal bite damage.'
);

const returnedToWalkAfterFinalPlant = await harness.stepUntil(
  () => {
    const currentZombie = harness
      .getObjects('Zombie')
      .find(instance => instance.id === finalZombie.id);
    const attacking = harness.getObjectVariable(
      finalZombie.id,
      'Attacking'
    )?.value;
    const targetX = harness.getObjectVariable(finalZombie.id, 'TargetX')?.value;
    const animation = currentZombie?.children?.ZombieModel?.[0]?.animation;
    return attacking === 0 && targetX === -100000 && animation === 'Walk';
  },
  { maxFrames: 12 }
);
harness.assert(
  returnedToWalkAfterFinalPlant,
  'After consuming the final plant, the zombie must clear its stale target and return to the Walk animation.'
);

harness.watch('Zombie');
harness.watch('SunflowerPlant');
